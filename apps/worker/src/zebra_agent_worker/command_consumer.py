from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from agent_core.application import SessionMessageAppendCommand, SessionMessageAppendService
from agent_core.contracts import SessionCommand, SessionCommandAcceptedPayload, SessionCommandKind
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.ports.projection_store import ProjectionStorePort
from agent_storage import ControlPlaneStores, LeaseConflictError
from pydantic import ValidationError

from zebra_agent_worker.recovery import SessionRecoveryError, SessionRecoveryService
from zebra_agent_worker.resume import SessionResumeError

if TYPE_CHECKING:
    from zebra_agent_worker.execution import SessionExecutionService


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
        stores: ControlPlaneStores,
        execution_service: SessionExecutionService,
    ) -> None:
        self._stores = stores
        self._projection_store: ProjectionStorePort = stores.sessions
        self._execution_service = execution_service
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
        for session in self._projection_store.list_recent_sessions(
            limit=max(1, batch_size * 8)
        ):
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
                if command.kind is SessionCommandKind.MESSAGE:
                    self._append_message(command)
                self._execution_service.execute_session(
                    command.session_id,
                    worker_id=worker_id,
                    lease_ttl_seconds=lease_ttl_seconds,
                )
            except (
                ValidationError,
                ValueError,
                LeaseConflictError,
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
        event = SessionMessageAppendService().build_event(
            session=recovery.session,
            next_sequence=recovery.session.current_sequence + 1,
            command=SessionMessageAppendCommand(
                content=content,
                clarification_id=clarification_id,
            ),
        ).model_copy(update={"idempotency_key": f"{command.idempotency_key}:message"})
        self._stores.events.append(event)


def _command_kind(event: object) -> str | None:
    payload = getattr(event, "payload", None)
    kind = payload.get("kind") if isinstance(payload, dict) else None
    return kind if isinstance(kind, str) else None
