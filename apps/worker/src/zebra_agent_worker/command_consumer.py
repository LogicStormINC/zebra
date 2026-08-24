from __future__ import annotations

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
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.ports.projection_store import ProjectionStorePort
from agent_storage import ControlPlaneStores, LeaseConflictError, PostgresControlPlaneStores
from pydantic import ValidationError

from zebra_agent_worker.control import SessionControlError
from zebra_agent_worker.recovery import SessionRecoveryError, SessionRecoveryService
from zebra_agent_worker.resume import SessionResumeError

if TYPE_CHECKING:
    from zebra_agent_worker.execution import SessionExecutionService


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
    ) -> None:
        self._stores = stores
        self._projection_store: ProjectionStorePort = stores.sessions
        self._execution_service = execution_service
        self._control_service = control_service
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
        for session in self._projection_store.list_recent_sessions(limit=max(1, batch_size * 8)):
            command_event = self._next_command(session.session_id, session.current_sequence)
            if command_event is None:
                continue
            try:
                accepted = SessionCommandAcceptedPayload.model_validate(command_event.payload)
                command = SessionCommand(
                    command_id=UUID(accepted.command_id),
                    session_id=SessionId(UUID(accepted.session_id)),
                    kind=accepted.kind,
                    expected_revision=accepted.expected_revision,
                    idempotency_key=accepted.idempotency_key,
                    payload=accepted.payload,
                )
                if command.kind in {SessionCommandKind.STOP, SessionCommandKind.CANCEL}:
                    self._cancel(command)
                elif command.kind is SessionCommandKind.SUSPEND:
                    self._suspend(command)
                elif command.kind is SessionCommandKind.MESSAGE:
                    self._append_message(command)
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
            except (
                ValidationError,
                ValueError,
                LeaseConflictError,
                SessionControlError,
                SessionRecoveryError,
                SessionResumeError,
            ) as exc:
                return CommandConsumption(
                    session_id=str(session.session_id),
                    command_kind=_command_kind(command_event),
                    status="skipped",
                    reason=str(exc),
                )
            return CommandConsumption(
                session_id=str(session.session_id),
                command_kind=command.kind.value,
                status="executed",
            )
        return CommandConsumption(session_id=None, command_kind=None, status="idle")

    def _next_command(self, session_id: SessionId, current_sequence: int) -> SessionEvent | None:
        for event in self._stores.events.read_since(session_id, current_sequence):
            if event.event_type is EventType.SESSION_COMMAND_ACCEPTED:
                return event
        return None

    def _append_message(self, command: SessionCommand) -> None:
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
                    open_turn_exists=current_turn(events) is not None,
                ),
            )
            .model_copy(update={"idempotency_key": f"{command.idempotency_key}:message"})
        )
        self._stores.events.append(event)

    def _cancel(self, command: SessionCommand) -> None:
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
