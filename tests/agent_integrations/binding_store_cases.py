"""Real adapter fixtures shared by binding-only persistence checks."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ag_ui.core import Event
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.context_capsule import ContextSourceEventRange
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.session_handoff import (
    HandoffActorKind,
    HandoffReason,
    SessionHandoffEnvelope,
)
from agent_core.domain.sessions import Session
from agent_core.ports.agent_tasks import AgentTaskPort, TaskEvent
from agent_core.ports.event_store import EventStorePort
from agent_core.ports.projection_store import ProjectionStorePort
from agent_core.ports.session_handoff import (
    SessionHandoffCommitRequest,
    SessionHandoffCreateRequest,
    SessionHandoffPort,
    canonical_handoff_request_hash,
)
from agent_core.ports.task_projection_checkpoints import ProjectionScope
from agent_core.ports.task_replay import TaskRunHeader
from agent_core.ports.workspace_projection_store import WorkspaceProjectionStorePort
from agent_integrations.ag_ui.binding_resolution import (
    advance_binding_resolution,
    binding_scope,
    binding_through,
)
from agent_integrations.ag_ui.checkpoint_binding import build_projection_page_plan
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.contracts import AgUiCursor, AgUiRunIdentity
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector

NOW = datetime(2026, 10, 3, tzinfo=UTC)


@dataclass(frozen=True)
class BindingStores:
    tasks: AgentTaskPort
    events: EventStorePort
    sessions: ProjectionStorePort
    workspaces: WorkspaceProjectionStorePort
    handoffs: SessionHandoffPort
    namespace: str
    cold: Callable[[], AgentTaskPort]
    fixture_attach: Callable[[TaskId, SessionId, SessionId], None] | None = None


def append(
    stores: BindingStores,
    segment: SessionId,
    sequence: int,
    kind: EventType,
    payload: dict[str, Any],
) -> SessionEvent:
    return stores.events.append(
        SessionEvent.create(
            session_id=segment,
            sequence=sequence,
            event_type=kind,
            actor=EventActor.HARNESS,
            payload=payload,
            created_at=NOW,
        )
    )


def command(stores: BindingStores, segment: SessionId, sequence: int, run: str = "run") -> None:
    append(
        stores,
        segment,
        sequence,
        EventType.SESSION_COMMAND_ACCEPTED,
        {
            "command_id": str(uuid4()),
            "session_id": str(segment),
            "kind": "run",
            "payload": {"run_id": run},
            "expected_revision": sequence - 1,
            "idempotency_key": f"binding-{run}",
            "fingerprint": "a" * 64,
        },
    )


def root(stores: BindingStores) -> SessionId:
    session = Session.create(title="binding", created_at=NOW)
    append(stores, session.session_id, 0, EventType.SESSION_CREATED, {"title": session.title})
    stores.sessions.save_session(session)
    stores.tasks.ensure_for_session(session.session_id)
    command(stores, session.session_id, 1)
    return session.session_id


def child(stores: BindingStores, task: TaskId, parent: SessionId) -> SessionId:
    session = Session.create(title="child", created_at=NOW)
    append(stores, session.session_id, 0, EventType.SESSION_CREATED, {"title": session.title})
    stores.sessions.save_session(session)
    if stores.fixture_attach is not None:
        stores.fixture_attach(task, session.session_id, parent)
    else:
        stores.tasks.attach_segment(
            task, session.session_id, predecessor_id=parent, reason=RolloverReason.RECOVERY
        )
    return session.session_id


def handoff(
    stores: BindingStores,
    segment: SessionId,
    sequence: int,
    kind: EventType,
    identity: UUID,
    peer: SessionId,
) -> None:
    payload: dict[str, Any] = {
        "handoff_id": str(identity),
        "artifact_id": "capsule",
        "checksum": "a" * 64,
    }
    if kind is EventType.SESSION_HANDOFF_COMMITTED:
        payload.update(
            {
                "target_session_id": str(peer),
                "reason": "internal_recovery",
                "target_stage_index": 1,
                "source_event_range": {"start_sequence": 0, "end_sequence": 1},
                "source_event_hash": "a" * 64,
                "idempotency_key_hash": "a" * 64,
            }
        )
    else:
        payload.update(
            {"parent_session_id": str(peer), "root_session_id": str(peer), "stage_index": 1}
        )
    append(stores, segment, sequence, kind, payload)


def prepare_native(stores: BindingStores, workspace: Path) -> SessionHandoffCommitRequest:
    boot = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="native binding",
            user_input="source",
            workspace_root=workspace,
            policy_profile="local-safe",
            created_at=NOW,
        )
    )
    source = boot.session.session_id
    for event in boot.events:
        stores.events.append(event)
    command(stores, source, 3)
    append(stores, source, 4, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    append(stores, source, 5, EventType.SESSION_COMPLETED, {"summary": "stage complete"})
    source_events = stores.events.list_for_session(source)  # Fixture construction only.
    stores.sessions.save_session(rebuild_session(source_events))
    stores.workspaces.save_workspace(rebuild_workspace(source_events))
    stores.tasks.ensure_for_session(source)
    create = SessionHandoffCreateRequest(
        source_session_id=source,
        idempotency_key="native-binding",
        title="child",
        reason=HandoffReason.OPERATOR_HANDOFF,
        stage_prompt="next stage",
        principal_identity_hash="principal",
        actor_kind=HandoffActorKind.OPERATOR,
        requested_authority=frozenset({"read"}),
    )
    facts = stores.handoffs.inspect_source_facts(source, at=NOW)
    operation = stores.handoffs.reserve(
        create,
        request_hash=canonical_handoff_request_hash(
            create, objective="binding", completed_work=(), pending_work=("next",)
        ),
        expected_source_stream_version=facts.stream_version,
        source_lease_fence=facts.lease_fence,
        authority_revision=facts.authority_revision,
        workspace_revision=facts.workspace_revision,
        task_profile_revision=facts.task_profile_revision,
        effective_depth_limit=facts.effective_depth_limit,
    )
    envelope = SessionHandoffEnvelope(
        handoff_id=operation.handoff_id,
        source_session_id=source,
        target_session_id=operation.target_session_id,
        root_session_id=source,
        source_stage_index=0,
        target_stage_index=1,
        reason=create.reason,
        objective="binding",
        completed_work=(),
        pending_work=("next",),
        immediate_next=create.stage_prompt,
        source_event_range=ContextSourceEventRange(
            start_sequence=0, end_sequence=facts.stream_version
        ),
        source_event_hash="a" * 64,
        workspace_revision=operation.workspace_revision,
        created_at=NOW,
        checksum="0" * 64,
    )
    return SessionHandoffCommitRequest(
        operation,
        create,
        envelope.model_copy(update={"checksum": envelope.expected_checksum()}),
        f"capsule-{operation.handoff_id}",
    )


def ready(tasks: AgentTaskPort, task: TaskId) -> TaskRunHeader:
    for maintenance in (
        tasks.backfill_event_positions,
        tasks.backfill_replay_headers,
        tasks.backfill_projection_sources,
    ):
        while not maintenance(task, limit=256):
            pass
    return tasks.read_run_header(task, "run")


def scope_for(stores: BindingStores, run: TaskRunHeader) -> ProjectionScope:
    assert run.anchor is not None
    return ProjectionScope(stores.namespace, run.task_id, run.anchor.event_id, "ag-ui-v1")


def resolve(tasks: AgentTaskPort, run: TaskRunHeader, scope: ProjectionScope) -> None:
    through = binding_through(run)
    head = tasks.read_checkpoint_head(binding_scope(scope))
    while head.through_sequence < through:
        updated = advance_binding_resolution(tasks, run, scope)
        assert updated.through_sequence > head.through_sequence
        head = updated


def publish(
    tasks: AgentTaskPort,
    run: TaskRunHeader,
    scope: ProjectionScope,
    *,
    end: int | None = None,
    closed_through: int | None = None,
) -> None:
    assert run.anchor is not None
    identity = AgUiRunIdentity(
        session_id=run.anchor.segment_id, thread_id=str(run.task_id), run_id=run.run_id
    )
    materializer = AgUiCheckpointMaterializer(tasks)
    after = tasks.read_checkpoint_head(scope).through_sequence
    through = run.highwater if end is None else end
    while after < through:
        page = tasks.read_event_page(
            run.task_id, after, limit=min(256, through - after), through_sequence=run.highwater
        )
        transition = materializer.prepare_page(
            page,
            build_projection_page_plan(
                tasks, page, run, scope, identity, closed_through=closed_through
            ),
            scope,
            identity,
        )
        assert transition is not None
        tasks.commit_projection_page(transition)
        after = page.next_sequence


def compare_oracle(
    tasks: AgentTaskPort,
    source: tuple[TaskEvent, ...],
    run: TaskRunHeader,
    scope: ProjectionScope,
    *,
    end: int | None = None,
) -> None:
    assert run.anchor is not None
    identity = AgUiRunIdentity(
        session_id=run.anchor.segment_id, thread_id=str(run.task_id), run_id=run.run_id
    )
    actual: list[tuple[AgUiCursor, Event]] = []
    materializer = AgUiCheckpointMaterializer(tasks)
    after = -1
    through = run.highwater if end is None else end
    while after < through:
        page = tasks.read_event_page(
            run.task_id, after, limit=min(256, through - after), through_sequence=run.highwater
        )
        for entry in page.events:
            header = tasks.read_event_projection_header(scope, entry.task_sequence)
            assert header is not None
            if header.eligible:
                actual.extend(materializer.iter_event_frames(scope, entry, identity, run=run))
        after = page.next_sequence
    assert actual == list(AgUiTaskProjector().project_task_events(source, identity))
