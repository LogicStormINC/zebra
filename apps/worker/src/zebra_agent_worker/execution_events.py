from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import CorrelationId
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.harness.models import HarnessEventDraft
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)

from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.tool_run_index import ToolRunIndexer

_INTERRUPTED_STATUSES = frozenset(
    {
        SessionStatus.SUSPENDED,
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    }
)


class ExecutionInterrupted(RuntimeError):
    """Raised when external durable control state stops live execution."""


class DurableHarnessEventRecorder:
    def __init__(
        self,
        *,
        session: Session,
        workspace: WorkspaceProjection,
        event_store: SQLiteEventStore,
        projection_store: SQLiteProjectionStore,
        workspace_store: SQLiteWorkspaceProjectionStore,
        model_call_indexer: ModelCallIndexer,
        tool_run_indexer: ToolRunIndexer,
    ) -> None:
        self._session = session
        self._workspace = workspace
        self._event_store = event_store
        self._projection_store = projection_store
        self._workspace_store = workspace_store
        self._model_call_indexer = model_call_indexer
        self._tool_run_indexer = tool_run_indexer
        self._events: list[SessionEvent] = []

    @property
    def session(self) -> Session:
        return self._session

    @property
    def workspace(self) -> WorkspaceProjection:
        return self._workspace

    @property
    def next_sequence(self) -> int:
        return self._session.current_sequence + 1

    @property
    def events(self) -> tuple[SessionEvent, ...]:
        return tuple(self._events)

    def append_draft(self, draft: HarnessEventDraft) -> SessionEvent:
        return self.append(
            draft.event_type,
            draft.actor,
            draft.payload,
        )

    def append(
        self,
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, object],
        *,
        created_at: datetime | None = None,
    ) -> SessionEvent:
        self._refresh_external_events()
        self._raise_if_interrupted()
        model_call_id = payload.get("model_call_id")
        correlation_id = _correlation_id(model_call_id)
        event = SessionEvent.create(
            session_id=self._session.session_id,
            sequence=self.next_sequence,
            event_type=event_type,
            actor=actor,
            payload=payload,
            correlation_id=correlation_id,
            created_at=created_at or datetime.now(UTC),
        )
        try:
            return self.append_event(event)
        except ValueError:
            self._refresh_external_events()
            self._raise_if_interrupted()
            raise

    def append_event(self, event: SessionEvent) -> SessionEvent:
        if event.session_id != self._session.session_id:
            raise ValueError("execution event session_id does not match recorder")
        if event.sequence != self.next_sequence:
            raise ValueError("execution event sequence does not match recorder")
        self._event_store.append(event)
        self._model_call_indexer.index_event(event)
        self._tool_run_indexer.index_event(event)
        self._session = apply_event(self._session, event)
        self._workspace = apply_workspace_event(self._workspace, event)
        self._projection_store.save_session(self._session)
        self._workspace_store.save_workspace(self._workspace)
        self._events.append(event)
        return event

    def _refresh_external_events(self) -> None:
        for event in self._event_store.read_since(
            self._session.session_id,
            self._session.current_sequence,
        ):
            self._session = apply_event(self._session, event)
            self._workspace = apply_workspace_event(self._workspace, event)

    def _raise_if_interrupted(self) -> None:
        if self._session.status in _INTERRUPTED_STATUSES:
            raise ExecutionInterrupted(
                f"execution interrupted by {self._session.status.value} session state"
            )


def _correlation_id(value: object) -> CorrelationId | None:
    if not isinstance(value, str):
        return None
    try:
        return CorrelationId(UUID(value))
    except ValueError:
        return None
