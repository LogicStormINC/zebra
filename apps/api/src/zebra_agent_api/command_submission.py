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
from agent_core.ports.extensions import ExtensionSkillConflictError
from agent_security.host_grant import HostGrantBindingError, VerifiedHostGrant
from agent_storage import ControlPlaneStores
from agent_storage.postgres.command_wakeup import CommandAdmissionCapacityError
from agent_storage.postgres.extensions import ExtensionSnapshotAdmissionConflictError
from pydantic import ValidationError

from zebra_agent_api.extension_turn_admission import (
    ClientExtensionBindingError,
    CloudExtensionTurnAdmission,
    PendingMessageCommandError,
)
from zebra_agent_api.responses import ApiResponse, bad_request, conflict

_COMMAND_FIELDS = frozenset({"command_id", "kind", "expected_revision", "payload"})


def submit_session_command(
    stores: ControlPlaneStores,
    session_id: str,
    payload: dict[str, object],
    *,
    idempotency_key: str | None,
    extension_admission: CloudExtensionTurnAdmission | None = None,
    verified_host_grant: VerifiedHostGrant | None = None,
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
    authorized_extensions = None
    needs_extensions = command.kind in {
        SessionCommandKind.MESSAGE,
        SessionCommandKind.RUN,
        SessionCommandKind.RESUME,
    }
    if needs_extensions and extension_admission is not None:
        if not isinstance(verified_host_grant, VerifiedHostGrant):
            return ApiResponse(
                status_code=403,
                body={"session_id": session_id, "status": "extension_authority_required"},
            )
        try:
            authorized_extensions = extension_admission.authorize(
                verified=verified_host_grant,
                session_id=session_key,
            )
        except HostGrantBindingError:
            return ApiResponse(
                status_code=403,
                body={"session_id": session_id, "status": "extension_authority_rejected"},
            )
        except Exception:
            return ApiResponse(
                status_code=503,
                body={"session_id": session_id, "status": "extension_admission_unavailable"},
            )
    existing = _existing_command_event(events, command.idempotency_key)
    decision = decide_session_command(
        command,
        current_revision=current_revision,
        existing_fingerprint=_existing_fingerprint(existing),
    )
    if decision.status is not SessionCommandStatus.ACCEPTED:
        return _decision_response(session_id, command, decision, existing)
    assert decision.event_type is EventType.SESSION_COMMAND_ACCEPTED
    scope = snapshot = task_ceiling = None
    if needs_extensions and extension_admission is not None:
        assert isinstance(verified_host_grant, VerifiedHostGrant)
        try:
            scope, snapshot, task_ceiling = extension_admission.prepare(
                verified=verified_host_grant,
                session_id=session_key,
                events=events,
                client_payload=command.payload,
                authorized=authorized_extensions,
                existing_turn=command.kind is not SessionCommandKind.MESSAGE,
            )
        except HostGrantBindingError:
            return ApiResponse(
                status_code=403,
                body={"session_id": session_id, "status": "extension_authority_rejected"},
            )
        except ClientExtensionBindingError as exc:
            return bad_request(str(exc))
        except PendingMessageCommandError:
            return conflict(
                session_id=session_id,
                status="message_pending",
                reason="the previous message command has not materialized",
            )
        except ExtensionSkillConflictError:
            return conflict(
                session_id=session_id,
                status="extension_configuration_conflict",
                reason="multiple enabled installations exist for one Skill",
            )
        except Exception:
            return ApiResponse(
                status_code=503,
                body={"session_id": session_id, "status": "extension_admission_unavailable"},
            )
    event = SessionEvent.create(
        session_id=session_key,
        sequence=current_revision + 1,
        event_type=decision.event_type,
        actor=EventActor.USER,
        payload=command.event_payload(
            extension_snapshot_digest=snapshot.digest if snapshot is not None else None,
            extension_turn_id=snapshot.turn_id if snapshot is not None else None,
        ),
        idempotency_key=command.idempotency_key,
    )
    try:
        if snapshot is None or scope is None or task_ceiling is None:
            persisted = stores.events.append(event)
        else:
            append = getattr(stores.events, "append_with_extension_snapshot", None)
            if append is None:
                return ApiResponse(
                    status_code=503,
                    body={"session_id": session_id, "status": "extension_admission_unavailable"},
                )
            persisted = append(
                event,
                scope=scope,
                snapshot=snapshot,
                task_ceiling=task_ceiling,
            )
    except ExtensionSnapshotAdmissionConflictError:
        return ApiResponse(
            status_code=409,
            body={"session_id": session_id, "status": "extension_configuration_changed"},
        )
    except CommandAdmissionCapacityError as exc:
        return ApiResponse(
            status_code=429 if exc.code == "command_scope_capacity" else 503,
            body={"session_id": session_id, "status": "capacity_limited", "reason": exc.code},
        )
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
