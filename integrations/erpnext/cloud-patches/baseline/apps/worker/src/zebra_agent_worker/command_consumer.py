from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from agent_core.application import (
    SessionMessageAppendCommand,
    SessionMessageAppendService,
    current_turn,
    project_turns,
)
from agent_core.contracts import SessionCommand, SessionCommandAcceptedPayload, SessionCommandKind
from agent_core.contracts.session_commands import validate_accepted_session_command
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.ports.projection_store import ProjectionStorePort
from agent_storage import ControlPlaneStores, LeaseConflictError, PostgresControlPlaneStores
from psycopg import OperationalError
from pydantic import ValidationError

from zebra_agent_worker.client_effect_continuation import pending_client_effect_ids
from zebra_agent_worker.command_rejections import (
    command_rejected,
    fail_rejected_continuation,
    reject_command,
)
from zebra_agent_worker.control import SessionControlError, UnsupportedSessionControlError
from zebra_agent_worker.recovery import SessionRecoveryError, SessionRecoveryService
from zebra_agent_worker.resume import SessionResumeError

if TYPE_CHECKING:
    from zebra_agent_worker.execution import SessionExecutionService

logger = logging.getLogger(__name__)


class _SessionControl(Protocol):
    def cancel_session(self, session_id: SessionId) -> object: ...

    def suspend_session(self, session_id: SessionId) -> object: ...


@dataclass(frozen=True)
class CommandConsumption:
    session_id: str | None
    command_kind: str | None
    status: str
    reason: str | None = None


class SessionCommandConsumer:
    """Consume the next unprojected command intent and wake the Worker."""

    def __init__(
        self,
        stores: ControlPlaneStores | PostgresControlPlaneStores,
        execution_service: SessionExecutionService,
        *,
        control_service: _SessionControl | None = None,
        cancel_command: Callable[[SessionCommand], object] | None = None,
        command_sessions: Callable[[int, SessionId | None], list[Session]] | None = None,
        next_command: Callable[[SessionId, int], SessionEvent | None] | None = None,
    ) -> None:
        self._stores = stores
        self._projection_store: ProjectionStorePort = stores.sessions
        self._execution_service = execution_service
        self._control_service = control_service
        self._cancel_command = cancel_command
        self._command_sessions = command_sessions
        self._command_reader = next_command
        self._scan_after: SessionId | None = None
        self._recovery = SessionRecoveryService(
            stores.events,
            stores.sessions,
            stores.workspaces,
        )

    def consume_once(
        self,
        *,
        worker_id: str,
        lease_ttl_seconds: int,
        batch_size: int = 1,
    ) -> CommandConsumption:
        limit = min(500, max(1, batch_size * 8))
        try:
            sessions = (
                self._command_sessions(limit, self._scan_after)
                if self._command_sessions is not None
                else self._projection_store.list_recent_sessions(limit=limit)
            )
        except (TimeoutError, OperationalError) as exc:
            logger.warning("Command candidate read deferred: %s", type(exc).__name__)
            return CommandConsumption(None, None, "deferred", "candidate_read_unavailable")
        if not sessions:
            self._scan_after = None
        skipped = None
        for session in sessions:
            previous = self._scan_after
            self._scan_after = session.session_id
            try:
                command_event = self._next_command(
                    session.session_id, session.current_sequence, session.status
                )
            except (TimeoutError, OperationalError) as exc:
                self._scan_after = previous
                logger.warning("Command event read deferred: %s", type(exc).__name__)
                return CommandConsumption(None, None, "deferred", "command_read_unavailable")
            if command_event is None:
                continue
            try:
                accepted = validate_accepted_session_command(
                    command_event.payload,
                    session_id=session.session_id,
                    idempotency_key=command_event.idempotency_key,
                )
                command = SessionCommand(
                    command_id=UUID(accepted.command_id),
                    session_id=SessionId(UUID(accepted.session_id)),
                    kind=accepted.kind,
                    expected_revision=accepted.expected_revision,
                    idempotency_key=accepted.idempotency_key,
                    payload=accepted.payload,
                )
            except ValueError:
                fail_rejected_continuation(self._stores.events, command_event)
                reject_command(self._stores.idempotency, command_event, "invalid_command")
                skipped = CommandConsumption(
                    str(session.session_id), _command_kind(command_event),
                    "skipped", "invalid_command",
                )
                continue
            try:
                if command.kind in {SessionCommandKind.STOP, SessionCommandKind.CANCEL}:
                    self._cancel(command)
                elif command.kind is SessionCommandKind.SUSPEND:
                    self._suspend(command)
                elif command.kind is SessionCommandKind.MESSAGE:
                    self._append_message(command, accepted)
                if command.kind in {
                    SessionCommandKind.RUN,
                    SessionCommandKind.RESUME,
                    SessionCommandKind.MESSAGE,
                }:
                    self._execution_service.execute_session(
                        command.session_id,
                        worker_id=_worker_id(command, worker_id),
                        lease_ttl_seconds=_lease_ttl(command, lease_ttl_seconds),
                    )
            except UnsupportedSessionControlError:
                reject_command(self._stores.idempotency, command_event, "unsupported_control")
                skipped = CommandConsumption(
                    str(session.session_id), command.kind.value, "skipped", "unsupported_control",
                )
                continue
            except (
                ValidationError,
                ValueError,
                LeaseConflictError,
                SessionControlError,
                SessionRecoveryError,
                SessionResumeError,
            ) as exc:
                skipped = CommandConsumption(
                    session_id=str(session.session_id),
                    command_kind=_command_kind(command_event),
                    status="skipped",
                    reason=str(exc),
                )
                continue
            return CommandConsumption(
                session_id=str(session.session_id),
                command_kind=command.kind.value,
                status="executed",
            )
        return skipped or CommandConsumption(session_id=None, command_kind=None, status="idle")

    def _next_command(
        self, session_id: SessionId, current_sequence: int, status: SessionStatus
    ) -> SessionEvent | None:
        if self._command_reader is not None:
            return self._command_reader(session_id, current_sequence)
        for event in self._stores.events.read_since(session_id, current_sequence):
            if event.event_type is EventType.SESSION_COMMAND_ACCEPTED and not command_rejected(
                self._stores.idempotency, event,
            ):
                return event
        if status is not SessionStatus.WAITING_CLIENT_EFFECT:
            return None
        # ponytail: scan one waiting session's stream only when the projection
        # passed a fast receipt; durable command cutover removes this O(n) fallback.
        events = self._stores.events.list_for_session(session_id)
        pending = set(pending_client_effect_ids(events))
        receipts = {
            event.payload.get("client_effect_id")
            for event in events
            if event.event_type is EventType.CLIENT_EFFECT_RECEIPT_ACCEPTED
        }
        for event in reversed(events):
            if event.event_type is not EventType.SESSION_COMMAND_ACCEPTED or command_rejected(
                self._stores.idempotency, event,
            ):
                continue
            result = event.payload.get("payload")
            effect = result.get("client_effect_result") if isinstance(result, dict) else None
            effect_id = effect.get("client_effect_id") if isinstance(effect, dict) else None
            if (
                event.actor is EventActor.HARNESS
                and event.payload.get("kind") == "resume"
                and isinstance(effect_id, str)
                and effect_id in pending
                and effect_id in receipts
            ):
                return event
        return None

    def _append_message(
        self, command: SessionCommand, accepted: SessionCommandAcceptedPayload
    ) -> None:
        recovery = self._recovery.recover_session(command.session_id)
        content = command.payload.get("content")
        if not isinstance(content, str):
            raise ValueError("message command content is invalid")
        clarification_id = command.payload.get("clarification_id")
        if clarification_id is not None and not isinstance(clarification_id, str):
            raise ValueError("message clarification_id is invalid")
        events = self._stores.events.list_for_session(command.session_id)
        event = (
            SessionMessageAppendService()
            .build_event(
                session=recovery.session,
                next_sequence=recovery.session.current_sequence + 1,
                command=SessionMessageAppendCommand(
                    content=content,
                    clarification_id=clarification_id,
                    prior_human_turns=len(project_turns(events)),
                    turn_id=accepted.extension_turn_id,
                    open_turn_exists=current_turn(events) is not None,
                    model_profile=_optional_string(command.payload.get("model_profile")),
                    reasoning_effort=_optional_string(command.payload.get("reasoning_effort")),
                ),
            )
            .model_copy(update={"idempotency_key": f"{command.idempotency_key}:message"})
        )
        self._stores.events.append(event)

    def _cancel(self, command: SessionCommand) -> None:
        if self._cancel_command is not None:
            self._cancel_command(command)
            return
        if self._control_service is None:
            raise SessionControlError("control service is not configured")
        self._control_service.cancel_session(command.session_id)

    def _suspend(self, command: SessionCommand) -> None:
        if self._control_service is None:
            raise SessionControlError("control service is not configured")
        self._control_service.suspend_session(command.session_id)


def _command_kind(event: object) -> str | None:
    payload = getattr(event, "payload", None)
    kind = payload.get("kind") if isinstance(payload, dict) else None
    return kind if isinstance(kind, str) else None


def _worker_id(command: SessionCommand, default: str) -> str:
    if command.kind is SessionCommandKind.RESUME:
        worker_id = command.payload.get("worker_id")
        if isinstance(worker_id, str) and worker_id.strip():
            return worker_id.strip()
    return default


def _lease_ttl(command: SessionCommand, default: int) -> int:
    if command.kind is SessionCommandKind.RESUME:
        lease_ttl = command.payload.get("lease_ttl_seconds")
        if isinstance(lease_ttl, int) and not isinstance(lease_ttl, bool) and lease_ttl > 0:
            return lease_ttl
    return default


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
