"""Cloud Worker selection of the trusted Context materialization boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from agent_core.application.memory_scopes import governed_memory_scope
from agent_core.application.turn_projection import is_human_message
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_materialization import (
    ContextMaterialization,
    ContextMaterializationMode,
    ContextMaterializationRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import WorkerLease
from agent_core.domain.memories import MemoryQuery
from agent_core.domain.sessions import Session
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports import EventStorePort
from agent_core.ports.context_materialization import ContextMaterializationPort
from agent_core.ports.execution_authority import ExecutionAuthorityResolverPort

from zebra_agent_worker.authority_types import AuthorityScopeProvider
from zebra_agent_worker.bound_execution_authority import (
    load_bound_binding,
    select_attempt_authority,
)
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_preparation import finish_preparation
from zebra_agent_worker.extension_recovery import (
    RecoveredTurnExtension,
    WorkerExtensionStore,
    recover_turn_extension,
)
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.runtime_authority import (
    attempt_authority_scope,
    persist_attempt_authority,
)
from zebra_agent_worker.task_recovery import RecoveredTask

CLOUD_CONTEXT_HISTORY_LIMIT = 20
CLOUD_CONTEXT_MEMORY_LIMIT = 8


@dataclass(frozen=True, slots=True)
class PreparedWorkerContext:
    claimed: ClaimedSession
    events: list[SessionEvent]
    binding: TaskBindingSnapshot | None
    materialization: ContextMaterialization | None
    extension: RecoveredTurnExtension | None


@dataclass(frozen=True)
class AttemptAuthorityEvidence:
    """Persist attempt authority evidence before Context materialization."""

    resolver: ExecutionAuthorityResolverPort | None
    static_scope: OpaqueAuthorityScope | None
    scope_provider: AuthorityScopeProvider | None
    recovery_service: SessionRecoveryService
    event_store: EventStorePort
    execution_input_reader: Callable[[WorkerLease], list[SessionEvent]] | None = None
    ownership_check: Callable[[], None] | None = None

    def persist(
        self,
        recorder: DurableHarnessEventRecorder,
        claimed: ClaimedSession,
        session_events: list[SessionEvent],
        *,
        session_id: SessionId,
        started_at: datetime,
        attempt_number: int = 1,
    ) -> tuple[ClaimedSession, list[SessionEvent]]:
        scope = attempt_authority_scope(
            self.static_scope,
            self.scope_provider,
            claimed.recovery.session,
        )
        if not persist_attempt_authority(
            recorder,
            self.resolver,
            scope,
            session_id=session_id,
            existing_events=session_events,
            attempt_number=attempt_number,
            created_at=started_at,
        ):
            return claimed, session_events
        return (
            ClaimedSession(
                recovery=finish_preparation(
                    lambda: self.recovery_service.recover_session(
                        session_id,
                        worker_lease=claimed.lease,
                    ),
                    self.ownership_check or recorder._ownership_check,
                ),
                lease=claimed.lease,
            ),
            _refresh_inputs(
                self.event_store,
                self.execution_input_reader,
                claimed.lease,
                recorder,
                self.ownership_check,
            ),
        )


def prepare_worker_context(
    *,
    store: ContextMaterializationPort | None,
    task_binding_loader: Callable[[SessionId], object] | None,
    resolver: ExecutionAuthorityResolverPort | None,
    static_scope: OpaqueAuthorityScope | None,
    scope_provider: AuthorityScopeProvider | None,
    recovery_service: SessionRecoveryService,
    event_store: EventStorePort,
    recorder: DurableHarnessEventRecorder,
    claimed: ClaimedSession,
    events: list[SessionEvent],
    task: RecoveredTask,
    active_capsule_id: str | None,
    as_of: datetime,
    extension_store: WorkerExtensionStore | None = None,
    allow_mcp: bool = False,
    attempt_number: int = 1,
    execution_input_reader: Callable[[WorkerLease], list[SessionEvent]] | None = None,
    ownership_check: Callable[[], None] | None = None,
) -> PreparedWorkerContext:
    session_id = claimed.lease.session_id
    binding = load_bound_binding(task_binding_loader, session_id)
    authority = select_attempt_authority(
        resolver,
        static_scope,
        scope_provider,
        task_binding_loader,
        session_id,
        binding=binding,
    )
    extension = recover_turn_extension(
        store=extension_store,
        events=events,
        session_id=session_id,
        task_binding=binding,
        allow_mcp=allow_mcp,
    )
    claimed, events = AttemptAuthorityEvidence(
        *authority,
        recovery_service,
        event_store,
        execution_input_reader,
        ownership_check,
    ).persist(
        recorder,
        claimed,
        events,
        session_id=session_id,
        started_at=as_of,
        attempt_number=attempt_number,
    )
    materialization = materialize_worker_context(
        store,
        scope=attempt_authority_scope(authority[1], authority[2], claimed.recovery.session),
        session=claimed.recovery.session,
        task=task,
        source_workspace_ref=str(claimed.recovery.workspace.workspace_root),
        active_capsule_id=active_capsule_id,
        events=events,
        as_of=as_of,
    )
    if materialization is not None:
        recorder.append(
            EventType.MEMORY_CONTEXT_SELECTED,
            EventActor.SYSTEM,
            {
                "selected_count": len(materialization.memories),
                "memory_ids": [str(item.record.memory_id) for item in materialization.memories],
                "query_has_text": (
                    materialization.request.memory_query is not None
                    and materialization.request.memory_query.text_query is not None
                ),
                "mode": materialization.request.mode.value,
            },
            created_at=as_of,
        )
        claimed = ClaimedSession(
            recovery=finish_preparation(
                lambda: recovery_service.recover_session(session_id, worker_lease=claimed.lease),
                ownership_check or recorder._ownership_check,
            ),
            lease=claimed.lease,
        )
        events = _refresh_inputs(
            event_store, execution_input_reader, claimed.lease, recorder, ownership_check
        )
    return PreparedWorkerContext(claimed, events, binding, materialization, extension)


def _refresh_inputs(
    event_store: EventStorePort,
    reader: Callable[[WorkerLease], list[SessionEvent]] | None,
    lease: WorkerLease,
    recorder: DurableHarnessEventRecorder,
    ownership_check: Callable[[], None] | None = None,
) -> list[SessionEvent]:
    if reader is None:
        return event_store.list_for_session(lease.session_id)
    # Retry only the derived input suffix after an authority/materialization
    # append. Never replay the canonical append or the materialization call.
    return finish_preparation(lambda: reader(lease), ownership_check or recorder._ownership_check)


def materialize_worker_context(
    store: ContextMaterializationPort | None,
    *,
    scope: OpaqueAuthorityScope | None,
    session: Session,
    task: RecoveredTask,
    source_workspace_ref: str,
    active_capsule_id: str | None,
    events: list[SessionEvent],
    as_of: datetime,
) -> ContextMaterialization | None:
    if store is None:
        return None
    if scope is None:
        raise ValueError("cloud Context materialization requires an authority scope")
    request = ContextMaterializationRequest(
        scope=scope,
        session_id=session.session_id,
        expected_session_revision=session.current_sequence,
        expected_active_capsule_id=active_capsule_id,
        as_of=as_of,
        mode=_mode(events),
        history_limit=CLOUD_CONTEXT_HISTORY_LIMIT,
        memory_query=_memory_query(task, source_workspace_ref),
    )
    return store.materialize(request)


def _memory_query(task: RecoveredTask, source_workspace_ref: str) -> MemoryQuery | None:
    scope = governed_memory_scope(
        fallback_repo_id=source_workspace_ref,
        host_context=task.host_context,
        definition_snapshot=task.definition_snapshot,
    )
    if scope is None:
        # Ambiguous Host principal binding fails closed: no cross-session Memory.
        return None
    return scope.query(text_query=task.user_input, limit=CLOUD_CONTEXT_MEMORY_LIMIT)


def _mode(events: list[SessionEvent]) -> ContextMaterializationMode:
    if any(
        event.event_type
        in {
            EventType.HARNESS_ATTEMPT_STARTED,
            EventType.SESSION_RESUMED,
            EventType.SESSION_SUSPENDED,
        }
        for event in events
    ):
        return ContextMaterializationMode.RECOVERY
    user_messages = sum(is_human_message(event) for event in events)
    return (
        ContextMaterializationMode.CONTINUE
        if user_messages > 1
        else ContextMaterializationMode.INITIAL
    )
