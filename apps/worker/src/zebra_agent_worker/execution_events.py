from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import CorrelationId
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports import (
    EventStorePort,
    ProjectionStorePort,
    WorkerMutationAuthority,
    WorkerProjectionTransactionPort,
    WorkspaceProjectionStorePort,
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
        event_store: EventStorePort,
        projection_store: ProjectionStorePort,
        workspace_store: WorkspaceProjectionStorePort,
        model_call_indexer: ModelCallIndexer,
        tool_run_indexer: ToolRunIndexer,
        ownership_check: Callable[[], None] | None = None,
        worker_projection_transaction: WorkerProjectionTransactionPort | None = None,
        worker_mutation_authority: WorkerMutationAuthority | None = None,
    ) -> None:
        if (worker_projection_transaction is None) != (worker_mutation_authority is None):
            raise ValueError(
                "worker projection transaction and mutation authority must be configured together"
            )
        self._session = session
        self._workspace = workspace
        self._event_store = event_store
        self._projection_store = projection_store
        self._workspace_store = workspace_store
        self._model_call_indexer = model_call_indexer
        self._tool_run_indexer = tool_run_indexer
        self._ownership_check = ownership_check or (lambda: None)
        self._worker_projection_transaction = worker_projection_transaction
        self._worker_mutation_authority = worker_mutation_authority
        self._events: list[SessionEvent] = []

    @property
    def session(self) -> Session:
        return self._session

    @property
    def workspace(self) -> WorkspaceProjection:
        return self._workspace

    @property
    def worker_mutation_authority(self) -> WorkerMutationAuthority | None:
        return self._worker_mutation_authority

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
        event = self.prepare(event_type, actor, payload, created_at=created_at)
        try:
            return self.append_event(event)
        except ValueError:
            self._refresh_external_events()
            self._raise_if_interrupted()
            raise

    def prepare(
        self,
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, object],
        *,
        created_at: datetime | None = None,
    ) -> SessionEvent:
        self._ownership_check()
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
        return event

    def append_event(self, event: SessionEvent) -> SessionEvent:
        self._ownership_check()
        if event.session_id != self._session.session_id:
            raise ValueError("execution event session_id does not match recorder")
        if event.sequence != self.next_sequence:
            raise ValueError("execution event sequence does not match recorder")
        if self._worker_projection_transaction is None:
            # The store returns the canonical event: an idempotent retry
            # that matches an earlier committed event replays that event,
            # and the projections advance on the canonical sequence.
            event = self._event_store.append(event)
            next_session = apply_event(self._session, event)
            next_workspace = apply_workspace_event(self._workspace, event)
            self._model_call_indexer.index_event(event)
            self._tool_run_indexer.index_event(event)
            self._session = next_session
            self._workspace = next_workspace
            self._projection_store.save_session(self._session)
            self._workspace_store.save_workspace(self._workspace)
        else:
            next_session = apply_event(self._session, event)
            next_workspace = apply_workspace_event(self._workspace, event)
            authority = self._worker_mutation_authority
            assert authority is not None
            committed = self._worker_projection_transaction.commit_worker_event(
                event,
                next_session,
                next_workspace,
                authority=authority,
            )
            event = committed.event
            self._model_call_indexer.index_worker_event(event, authority=authority)
            self._tool_run_indexer.index_worker_event(event, authority=authority)
            self._session = committed.session
            self._workspace = committed.workspace
        self._advance_authority(event)
        self._events.append(event)
        return event

    def accept_persisted_event(self, event: SessionEvent) -> SessionEvent:
        """Advance projections for an event committed by another atomic store."""
        self._ownership_check()
        if event.session_id != self._session.session_id:
            raise ValueError("execution event session_id does not match recorder")
        if event.sequence != self.next_sequence:
            raise ValueError("execution event sequence does not match recorder")
        authority = self._worker_mutation_authority
        if authority is None:
            self._model_call_indexer.index_event(event)
            self._tool_run_indexer.index_event(event)
            self._session = apply_event(self._session, event)
            self._workspace = apply_workspace_event(self._workspace, event)
            self._projection_store.save_session(self._session)
            self._workspace_store.save_workspace(self._workspace)
        else:
            assert self._worker_projection_transaction is not None
            next_session = apply_event(self._session, event)
            next_workspace = apply_workspace_event(self._workspace, event)
            committed = self._worker_projection_transaction.project_persisted_worker_event(
                event,
                next_session,
                next_workspace,
                authority=authority,
            )
            event = committed.event
            self._model_call_indexer.index_worker_event(event, authority=authority)
            self._tool_run_indexer.index_worker_event(event, authority=authority)
            self._session = committed.session
            self._workspace = committed.workspace
        self._advance_authority(event)
        self._events.append(event)
        return event

    def accept_committed_aggregate(
        self,
        event: SessionEvent,
        *,
        session: Session,
        workspace: WorkspaceProjection,
    ) -> SessionEvent:
        """Accept a cloud aggregate result without a second projection save."""
        self._ownership_check()
        authority = self._worker_mutation_authority
        if authority is None or self._worker_projection_transaction is None:
            raise ValueError("cloud aggregate acceptance requires Worker mutation authority")
        if event.session_id != self._session.session_id or event.sequence != self.next_sequence:
            raise ValueError("cloud aggregate Event sequence does not match recorder")
        expected_session = apply_event(self._session, event)
        expected_workspace = apply_workspace_event(self._workspace, event)
        if session != expected_session or workspace != expected_workspace:
            raise ValueError("cloud aggregate projections do not match Event replay")
        self._model_call_indexer.index_worker_event(event, authority=authority)
        self._tool_run_indexer.index_worker_event(event, authority=authority)
        self._session = session
        self._workspace = workspace
        self._advance_authority(event)
        self._events.append(event)
        return event

    def accept_committed_events(
        self,
        events: tuple[SessionEvent, ...],
        *,
        session: Session,
        workspace: WorkspaceProjection,
    ) -> None:
        """Accept Events whose primary projections committed in the same transaction."""
        for event in events:
            if event.session_id != self._session.session_id or event.sequence != self.next_sequence:
                raise ValueError("committed Context Event sequence does not match recorder")
            authority = self._worker_mutation_authority
            if authority is None:
                self._model_call_indexer.index_event(event)
                self._tool_run_indexer.index_event(event)
            else:
                self._model_call_indexer.index_worker_event(event, authority=authority)
                self._tool_run_indexer.index_worker_event(event, authority=authority)
            self._advance_authority(event)
            self._events.append(event)
            self._session = apply_event(self._session, event)
            self._workspace = apply_workspace_event(self._workspace, event)
        if self._session != session or self._workspace != workspace:
            raise ValueError("committed Context projections do not match Event replay")

    def _refresh_external_events(self) -> None:
        for event in self._event_store.read_since(
            self._session.session_id,
            self._session.current_sequence,
        ):
            self._session = apply_event(self._session, event)
            self._workspace = apply_workspace_event(self._workspace, event)
            self._advance_authority(event)

    def _advance_authority(self, event: SessionEvent) -> None:
        if self._worker_mutation_authority is not None:
            self._worker_mutation_authority = self._worker_mutation_authority.model_copy(
                update={"expected_stream_revision": event.sequence}
            )

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
