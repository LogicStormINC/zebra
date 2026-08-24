"""Cloud Worker selection of the trusted Context materialization boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_materialization import (
    ContextMaterialization,
    ContextMaterializationMode,
    ContextMaterializationRequest,
)
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.memories import MemoryQuery, MemoryStatus, MemoryVisibility
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
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.runtime_authority import (
    AttemptAuthorityEvidence,
    attempt_authority_scope,
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
    claimed, events = AttemptAuthorityEvidence(
        *authority,
        recovery_service,
        event_store,
    ).persist(
        recorder,
        claimed,
        events,
        session_id=session_id,
        started_at=as_of,
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
    return PreparedWorkerContext(claimed, events, binding, materialization)


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


def _memory_query(task: RecoveredTask, source_workspace_ref: str) -> MemoryQuery:
    snapshot = task.definition_snapshot
    if snapshot is not None:
        return MemoryQuery(
            authority_issuer=snapshot.authority_issuer,
            namespace_id=snapshot.namespace_id,
            definition_id=snapshot.definition_id,
            text_query=task.user_input,
            statuses=(MemoryStatus.CONFIRMED,),
            limit=CLOUD_CONTEXT_MEMORY_LIMIT,
        )
    return MemoryQuery(
        repo_id=source_workspace_ref,
        visibility=MemoryVisibility.REPO,
        text_query=task.user_input,
        statuses=(MemoryStatus.CONFIRMED,),
        limit=CLOUD_CONTEXT_MEMORY_LIMIT,
    )


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
    user_messages = sum(
        event.event_type is EventType.USER_MESSAGE_RECEIVED
        and event.payload.get("actor_kind") != "automation"
        and event.payload.get("source") != "session_handoff"
        for event in events
    )
    return (
        ContextMaterializationMode.CONTINUE
        if user_messages > 1
        else ContextMaterializationMode.INITIAL
    )
