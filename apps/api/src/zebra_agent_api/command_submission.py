from __future__ import annotations

from uuid import UUID, uuid4

from agent_core.contracts import (
    SessionCommand,
    SessionCommandDecision,
    SessionCommandKind,
    SessionCommandStatus,
    decide_session_command,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_storage import ControlPlaneStores
from pydantic import ValidationError

from zebra_agent_api.responses import ApiResponse, bad_request, conflict

_COMMAND_FIELDS = frozenset({"command_id", "kind", "expected_revision", "payload"})


def submit_session_command(
    stores: ControlPlaneStores,
    session_id: str,
    payload: dict[str, object],
    *,
    idempotency_key: str | None,
) -> ApiResponse:
    try:
        session_key = SessionId(UUID(session_id))
    except ValueError:
        return bad_request("session_id must be a UUID")
    if idempotency_key is None or not idempotency_key.strip():
        return bad_request("Idempotency-Key header is required")
    unknown_fields = sorted(payload.keys() - _COMMAND_FIELDS)
    if unknown_fields:
        return bad_request(f"unknown command fields: {', '.join(unknown_fields)}")
    if stores.sessions.get_session(session_key) is None:
        return ApiResponse(
            status_code=404,
            body={"session_id": session_id, "status": "not_found"},
        )
    try:
        command = SessionCommand(
            command_id=_command_id(payload.get("command_id")),
            session_id=session_key,
            kind=_command_kind(payload.get("kind")),
            expected_revision=_expected_revision(payload.get("expected_revision")),
            idempotency_key=idempotency_key,
            payload=_command_payload(payload.get("payload")),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        return bad_request(str(exc))

    events = stores.events.list_for_session(session_key)
    if not events:
        return ApiResponse(
            status_code=409,
            body={"session_id": session_id, "status": "revision_conflict"},
        )
    current_revision = events[-1].sequence
    existing = _existing_command_event(events, command.idempotency_key)
    decision = decide_session_command(
        command,
        current_revision=current_revision,
        existing_fingerprint=_existing_fingerprint(existing),
    )
    if decision.status is not SessionCommandStatus.ACCEPTED:
        return _decision_response(session_id, command, decision, existing)
    assert decision.event_type is EventType.SESSION_COMMAND_ACCEPTED
    event = SessionEvent.create(
        session_id=session_key,
        sequence=current_revision + 1,
        event_type=decision.event_type,
        actor=EventActor.USER,
        payload=command.event_payload(),
        idempotency_key=command.idempotency_key,
    )
    try:
        persisted = stores.events.append(event)
    except ValueError:
        return _retry_after_append_race(stores, session_key, session_id, command)
    return _accepted_response(session_id, command, persisted)


def _retry_after_append_race(
    stores: ControlPlaneStores,
    session_id: SessionId,
    session_text: str,
    command: SessionCommand,
) -> ApiResponse:
    events = stores.events.list_for_session(session_id)
    existing = _existing_command_event(events, command.idempotency_key)
    if existing is not None:
        decision = decide_session_command(
            command,
            current_revision=events[-1].sequence if events else 0,
            existing_fingerprint=_existing_fingerprint(existing),
        )
        return _decision_response(session_text, command, decision, existing)
    current_revision = events[-1].sequence if events else 0
    return conflict(
        session_id=session_text,
        status=SessionCommandStatus.REVISION_CONFLICT.value,
        reason=f"command stream advanced to revision {current_revision}",
    )


def _decision_response(
    session_id: str,
    command: SessionCommand,
    decision: SessionCommandDecision,
    existing: SessionEvent | None,
) -> ApiResponse:
    status = decision.status.value
    body: dict[str, object] = {
        "session_id": session_id,
        "command_id": str(command.command_id),
        "kind": command.kind.value,
        "status": status,
        "expected_revision": command.expected_revision,
        "current_revision": decision.current_revision,
    }
    if decision.reason is not None:
        body["reason"] = decision.reason
    if existing is not None:
        body["event_sequence"] = existing.sequence
        existing_command_id = existing.payload.get("command_id")
        if isinstance(existing_command_id, str):
            body["command_id"] = existing_command_id
    return ApiResponse(status_code=200 if status == "duplicate" else 409, body=body)


def _accepted_response(
    session_id: str,
    command: SessionCommand,
    event: SessionEvent,
) -> ApiResponse:
    return ApiResponse(
        status_code=202,
        body={
            "session_id": session_id,
            "command_id": str(command.command_id),
            "kind": command.kind.value,
            "status": SessionCommandStatus.ACCEPTED.value,
            "event_type": event.event_type.value,
            "event_sequence": event.sequence,
            "expected_revision": command.expected_revision,
        },
    )


def _existing_command_event(events: list[SessionEvent], key: str) -> SessionEvent | None:
    return next((event for event in events if event.idempotency_key == key), None)


def _existing_fingerprint(event: SessionEvent | None) -> str | None:
    if event is None:
        return None
    fingerprint = event.payload.get("fingerprint")
    return fingerprint if isinstance(fingerprint, str) else "__non_command_event__"


def _command_id(value: object) -> UUID:
    if value is None:
        return uuid4()
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise ValueError("command_id must be a UUID when provided")


def _command_payload(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("payload must be an object")
    return dict(value)


def _command_kind(value: object) -> SessionCommandKind:
    if not isinstance(value, str):
        raise ValueError("kind must be a supported command string")
    try:
        return SessionCommandKind(value)
    except ValueError as exc:
        raise ValueError("kind must be a supported command string") from exc


def _expected_revision(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("expected_revision must be a non-negative integer")
    return value
