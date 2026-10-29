from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from datetime import UTC, datetime
from functools import wraps
from threading import RLock
from time import monotonic
from typing import Concatenate
from uuid import UUID

from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import CorrelationId, SessionId
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
from agent_core.ports.session_recovery import SessionEventPage
from agent_core.ports.workspace_projection_store import WorkerProjectionBatchPort
from agent_storage.postgres.task_io import current_task_io_deadline, task_io_deadline

from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.public_output_runtime import publication_lock
from zebra_agent_worker.tool_run_index import ToolRunIndexer

_LOGGER = logging.getLogger(__name__)
_INTERRUPTED_STATUSES = frozenset(
    {
        SessionStatus.SUSPENDED,
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    }
)


def _serialized[**P, R](
    method: Callable[Concatenate[DurableHarnessEventRecorder, P], R],
) -> Callable[Concatenate[DurableHarnessEventRecorder, P], R]:
    @wraps(method)
    def call(recorder: DurableHarnessEventRecorder, /, *args: P.args, **kwargs: P.kwargs) -> R:
        started, entered = monotonic(), None
        try:
            with recorder.mutation():
                entered = monotonic()
                return method(recorder, *args, **kwargs)
        finally:
            ended = monotonic()
            if ended - started >= 0.25:
                _LOGGER.warning(
                    "slow_worker_mutation operation=%s admission_ms=%d operation_ms=%d total_ms=%d",
                    method.__name__,
                    int(((entered if entered is not None else ended) - started) * 1000),
                    int((ended - entered) * 1000) if entered is not None else 0,
                    int((ended - started) * 1000),
                )

    return call


class ExecutionInterrupted(RuntimeError):
    """Raised when external durable control state stops live execution."""

    def __init__(self, message: str, *, session: Session | None = None) -> None:
        super().__init__(message)
        self.session = session


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
        tail_reader: Callable[[WorkerMutationAuthority, int | None], SessionEventPage]
        | None = None,
        execution_status_reader: Callable[[SessionId], SessionStatus | None] | None = None,
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
        if tail_reader is not None and worker_mutation_authority is None:
            raise ValueError("bounded tail reader requires worker mutation authority")
        self._tail_reader = tail_reader
        self._execution_status_reader = execution_status_reader
        self._tail_highwater: int | None = None
        self._events: list[SessionEvent] = []
        # Durable client-effect admissions committed atomically by an
        # execution-side adapter; the harness draft echo of the same effect
        # must not duplicate them on the Event stream.
        self._admitted_client_effects: dict[str, SessionEvent] = {}
        # Timer and execution callbacks share the same per-recorder, reentrant boundary.
        self._mutation_lock = RLock()
        self.effect_started_listener: Callable[[str], None] | None = None

    def effect_started(self, call_id: str) -> None:
        # Called outside mutation(), after durable intent and ownership checks.
        if self.effect_started_listener is not None:
            self.effect_started_listener(call_id)

    @_serialized
    def require_active_execution(self) -> None:
        if self._execution_status_reader is None:
            self.read_active_session()
            return
        status = self._execution_status_reader(self._session.session_id)
        if status is None:
            raise ValueError("execution control projection is missing")
        if status in _INTERRUPTED_STATUSES:
            # Preserve the original fresh Session/error path for control transitions.
            self.read_active_session()
            return
        self._ownership_check()

    @_serialized
    def read_active_session(self) -> Session:
        """Poll primary control state without replaying or projecting historical Events."""
        session = self._projection_store.get_session(self._session.session_id)
        if session is None:
            raise ValueError("execution control projection is missing")
        if session.status in _INTERRUPTED_STATUSES:
            raise ExecutionInterrupted(
                f"execution interrupted by {session.status.value} session state", session=session
            )
        self._ownership_check()
        return session

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

    @contextmanager
    def mutation(self) -> Iterator[None]:
        """Bind external prepare/commit/accept to the timer's append boundary."""
        with publication_lock(
            self._mutation_lock, bounded=self._worker_mutation_authority is not None
        ):
            yield

    def append_draft(self, draft: HarnessEventDraft) -> SessionEvent:
        return self.append(
            draft.event_type,
            draft.actor,
            draft.payload,
        )

    @_serialized
    def append(
        self,
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, object],
        *,
        created_at: datetime | None = None,
    ) -> SessionEvent:
        event = self.prepare(event_type, actor, payload, created_at=created_at)
        if event.event_type is EventType.CLIENT_EFFECT_SCHEDULED:
            effect_id = event.payload.get("client_effect_id")
            admitted = (
                self._admitted_client_effects.get(effect_id)
                if isinstance(effect_id, str)
                else None
            )
            if admitted is not None:
                # The dispatch already committed the durable admission Event
                # atomically with its effects row; persisting the harness echo
                # would duplicate the schedule fact on the stream. Checked
                # after prepare so a just-adopted external admission from the
                # crash window is still honored here.
                return admitted
        try:
            return self.append_event(event)
        except ValueError:
            self._synchronize_external_events()
            self._raise_if_interrupted()
            raise

    @_serialized
    def prepare(
        self,
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, object],
        *,
        created_at: datetime | None = None,
    ) -> SessionEvent:
        self._ownership_check()
        self._synchronize_external_events()
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

    @_serialized
    def append_event(self, event: SessionEvent) -> SessionEvent:
        self._ownership_check()
        if event.session_id != self._session.session_id:
            raise ValueError("execution event session_id does not match recorder")
        if event.sequence != self.next_sequence:
            raise ValueError("execution event sequence does not match recorder")
        if self._worker_projection_transaction is None:
            # Pre-validate the requested event BEFORE anything persists, so
            # an illegal transition never pollutes the Event Store.
            apply_event(self._session, event)
            apply_workspace_event(self._workspace, event)
            canonical = self._event_store.append(event)
            if canonical.sequence <= self._session.current_sequence:
                # An idempotent retry returned an event the projection
                # already covers: treat it as processed — no replay, no
                # index rebuild, no projection rollback.
                self._events.append(canonical)
                return canonical
            event = canonical
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

    @_serialized
    def accept_persisted_event(self, event: SessionEvent) -> SessionEvent:
        """Advance projections for an event committed by another atomic store."""
        self._ownership_check()
        if event.session_id != self._session.session_id:
            raise ValueError("execution event session_id does not match recorder")
        if event.sequence != self.next_sequence:
            raise ValueError("execution event sequence does not match recorder")
        self._note_admitted_client_effect(event)
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

    @_serialized
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

    @_serialized
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
            self._note_admitted_client_effect(event)
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

    @_serialized
    def refresh_tail(self) -> None:
        """Adopt externally committed events into recorder memory only.

        Used after accepting a fenced receipt when later events (e.g. the
        next human message) were already committed and projected by
        another writer: the recorder catches up WITHOUT writing primary
        projections again. Terminal control states are legitimate here —
        this is recovery bookkeeping, not an execution gate.
        """
        self._ownership_check()
        self._refresh_external_events()

    @_serialized
    def project_persisted_tail(self) -> None:
        """Project events atomically persisted by an execution-side adapter.

        Client-effect scheduling and receipt acceptance deliberately commit
        their own durable rows and Events together.  Before finalization the
        Worker must advance the primary projections across that canonical tail
        or its next fenced Event would skip revisions.
        """

        with self._tail_budget():
            if (self._tail_reader is not None
                    and isinstance(self._worker_projection_transaction, WorkerProjectionBatchPort)):
                from zebra_agent_worker.execution_tail_batches import project_tail_batches

                project_tail_batches(self)
                return
            for event in self._external_tail():
                self.accept_persisted_event(event)

    def _synchronize_external_events(self) -> None:
        if self._worker_projection_transaction is None:
            self._refresh_external_events()
            return
        self.project_persisted_tail()

    def _refresh_external_events(self) -> None:
        with self._tail_budget():
            for event in self._external_tail():
                self._session = apply_event(self._session, event)
                self._workspace = apply_workspace_event(self._workspace, event)
                self._advance_authority(event)
                self._note_admitted_client_effect(event)

    def _note_admitted_client_effect(self, event: SessionEvent) -> None:
        if event.event_type is not EventType.CLIENT_EFFECT_SCHEDULED:
            return
        effect_id = event.payload.get("client_effect_id")
        if isinstance(effect_id, str) and effect_id:
            self._admitted_client_effects[effect_id] = event

    def _tail_budget(self) -> AbstractContextManager[None]:
        return task_io_deadline(monotonic() + 2) if self._tail_reader else nullcontext()

    def _external_tail(self) -> Iterator[SessionEvent]:
        if self._tail_reader is None:
            yield from self._event_store.read_since(
                self._session.session_id, self._session.current_sequence
            )
            return
        highwater = self._tail_highwater
        while True:
            self._ownership_check()
            authority = self._worker_mutation_authority
            assert authority is not None
            after = self._session.current_sequence
            if authority.expected_stream_revision != after:
                raise ValueError("recorder tail authority revision diverges")
            page = self._tail_reader(authority, highwater)
            if (
                page.session_id != self._session.session_id
                or page.after_sequence != after
                or (highwater is not None and page.highwater != highwater)
            ):
                raise ValueError("recorder tail page changed its admitted frontier")
            highwater = page.highwater
            self._tail_highwater = highwater
            for event in page.events:
                if event.session_id != self._session.session_id or event.sequence != after + 1:
                    raise ValueError("recorder tail page skips canonical revisions")
                self._ownership_check()
                deadline = current_task_io_deadline()
                if deadline is not None and monotonic() >= deadline:
                    raise TimeoutError("Recorder canonical tail deadline exceeded")
                yield event
                after = event.sequence
            if after == highwater:
                self._tail_highwater = None
                return
            if not page.events:
                raise ValueError("recorder tail page made no progress")

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
