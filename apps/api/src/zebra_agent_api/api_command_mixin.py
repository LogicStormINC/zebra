from __future__ import annotations

from hashlib import sha256
from typing import Protocol
from uuid import UUID

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_storage import ControlPlaneStores

from zebra_agent_api.command_submission import submit_session_command
from zebra_agent_api.responses import ApiResponse, conflict


class _CommandApp(Protocol):
    stores: ControlPlaneStores


class _RunEventMismatch:
    """Sentinel: the key is taken by an event that is not OUR run command."""


_RUN_EVENT_MISMATCH = _RunEventMismatch()


class ApiCommandMixin:
    def queue_cloud_run(
        self: _CommandApp,
        response: ApiResponse,
        *,
        idempotency_key: str | None,
    ) -> ApiResponse:
        if response.status_code != 201:
            return response
        session_text = response.body.get("session_id")
        if not isinstance(session_text, str):
            return response
        try:
            session_id = UUID(session_text)
        except ValueError:
            return response
        events = self.stores.events.list_for_session(SessionId(session_id))
        if not events:
            return response
        command_key = _bounded_run_key(idempotency_key, session_text)
        # A run event committed by a concurrent create or by a request
        # that crashed before the receipt body synced must NOT be
        # re-submitted: the stream head has advanced past its
        # expected_revision, so a fresh submission returns
        # idempotency_conflict instead of duplicate. Only a FULLY
        # validated persisted run command may be rebuilt — the same key
        # held by any other meaning stays a conflict.
        existing = _persisted_run_event(events, command_key, session_text)
        if existing is _RUN_EVENT_MISMATCH:
            return _run_key_conflict(session_text)
        if existing is not None:
            command = _accepted_from_event(existing, session_text)
        else:
            command = submit_session_command(
                self.stores,
                session_text,
                {"kind": "run", "expected_revision": events[-1].sequence},
                idempotency_key=command_key,
            )
            if command.status_code != 202:
                if command.body.get("status") == "duplicate":
                    # Narrow race: the event landed between our list and
                    # the submission — re-validate the persisted row.
                    events = self.stores.events.list_for_session(SessionId(session_id))
                    existing = _persisted_run_event(events, command_key, session_text)
                    if existing is _RUN_EVENT_MISMATCH:
                        return _run_key_conflict(session_text)
                    if existing is None:
                        return command
                    command = _accepted_from_event(existing, session_text)
                else:
                    return command
        body = dict(response.body)
        body.update({"executed": False, "status": "queued", "command": command.body})
        return ApiResponse(status_code=201, body=body)

    def submit_command(
        self: _CommandApp,
        session_id: str,
        payload: dict[str, object],
        *,
        idempotency_key: str | None,
    ) -> ApiResponse:
        """Append intent only; a Worker owns the eventual execution side effect."""
        return submit_session_command(
            self.stores,
            session_id,
            payload,
            idempotency_key=idempotency_key,
        )


def _persisted_run_event(
    events: list[SessionEvent], command_key: str, session_text: str
) -> SessionEvent | _RunEventMismatch | None:
    """Return the persisted run command for this key, a mismatch
    sentinel when the key is held by another meaning, or None."""

    for event in events:
        if event.idempotency_key != command_key:
            continue
        if (
            event.event_type is not EventType.SESSION_COMMAND_ACCEPTED
            or not _is_genuine_run_event(event, command_key, session_text)
        ):
            return _RUN_EVENT_MISMATCH
        return event
    return None


def _is_genuine_run_event(event: SessionEvent, command_key: str, session_text: str) -> bool:
    """Full business validation through the CORE contract, not a local
    copy: the payload must parse as a SessionCommandAcceptedPayload
    (UUID command/session ids, enum kind, bounded fields), rebuild into
    a SessionCommand, and the accepted fingerprint must equal the
    command's own core-computed fingerprint. Any malformation —
    including a self-consistent fingerprint around a non-UUID
    command_id — fails closed."""

    from agent_core.contracts import (
        SessionCommand,
        SessionCommandAcceptedPayload,
        SessionCommandKind,
    )
    from pydantic import ValidationError

    try:
        accepted = SessionCommandAcceptedPayload.model_validate(event.payload)
        command = SessionCommand(
            command_id=UUID(accepted.command_id),
            session_id=SessionId(UUID(accepted.session_id)),
            kind=accepted.kind,
            expected_revision=accepted.expected_revision,
            idempotency_key=accepted.idempotency_key,
            payload=accepted.payload,
        )
    except (ValidationError, ValueError):
        return False
    if command.kind is not SessionCommandKind.RUN:
        return False
    if command.idempotency_key != command_key:
        return False
    if str(command.session_id) != session_text:
        return False
    if command.payload != {}:
        return False
    return accepted.fingerprint == command.fingerprint


def _run_key_conflict(session_text: str) -> ApiResponse:
    return conflict(
        session_id=session_text,
        status="idempotency_conflict",
        reason="command key is held by a different command meaning",
    )


def _accepted_from_event(event: object, session_text: str) -> ApiResponse:
    """Rebuild the 202-accepted command body from the persisted event."""

    payload = getattr(event, "payload", {})
    return ApiResponse(
        status_code=202,
        body={
            "session_id": session_text,
            "command_id": payload.get("command_id"),
            "kind": payload.get("kind", "run"),
            "status": "accepted",
            "event_type": "session_command_accepted",
            "event_sequence": getattr(event, "sequence", None),
            "expected_revision": payload.get("expected_revision"),
        },
    )


def _bounded_run_key(idempotency_key: str | None, session_text: str) -> str:
    """Keep the derived run key inside the 256-char command contract.

    Appending ":run" to a legal 253-256-char Idempotency-Key would push
    the derived command key past the SessionCommand limit AFTER the
    create already committed; long keys switch to a fixed-length digest
    form that stays deterministic per key.
    """

    if not idempotency_key:
        return f"run:{session_text}"
    if len(idempotency_key) + len(":run") <= 256:
        return f"{idempotency_key}:run"
    digest = sha256(idempotency_key.encode()).hexdigest()
    return f"zebra-run:{digest}"
