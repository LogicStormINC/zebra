"""Actual SQLite/isolated PG binding persistence; complete native replay oracle."""

from dataclasses import replace
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_core.ports.task_replay import TaskEventHeader, TaskRunHeader
from agent_integrations.ag_ui.binding_resolution import (
    BindingResolutionPending,
    advance_binding_resolution,
    binding_scope,
)
from agent_integrations.ag_ui.checkpoint_binding import build_projection_page_plan
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_plan import ProjectionEventPlan, ProjectionPagePlan
from agent_integrations.ag_ui.contracts import AgUiProjectionError, AgUiRunIdentity
from agent_storage import (
    PostgresAgentTaskStore,
    PostgresEventStore,
    PostgresProjectionStore,
    PostgresSessionHandoffStore,
    PostgresWorkspaceProjectionStore,
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteSessionHandoffStore,
    SQLiteWorkspaceProjectionStore,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.task_index_transactions import attach_segment_in_transaction

from tests.agent_integrations.binding_store_cases import (
    BindingStores,
    append,
    child,
    command,
    compare_oracle,
    handoff,
    prepare_native,
    publish,
    ready,
    resolve,
    root,
    scope_for,
)
from tests.agent_storage.test_postgres_projection_source_metadata import (
    metadata_dsn as metadata_dsn,
)


@pytest.fixture(params=("sqlite", "postgres"))
def stores(request: pytest.FixtureRequest, tmp_path: Path) -> BindingStores:
    if request.param == "sqlite":
        path = tmp_path / "binding-persistence.sqlite"
        return BindingStores(
            SQLiteAgentTaskStore(path),
            SQLiteEventStore(path),
            SQLiteProjectionStore(path),
            SQLiteWorkspaceProjectionStore(path),
            SQLiteSessionHandoffStore(path),
            "local",
            lambda: SQLiteAgentTaskStore(path),
        )
    dsn = request.getfixturevalue("metadata_dsn")
    assert isinstance(dsn, str)
    namespace = f"binding-persistence-{uuid4().hex}"
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)

    def fixture_attach(task: TaskId, segment: SessionId, parent: SessionId) -> None:
        # Historical graph setup only. Native Handoff uses the fenced aggregate above.
        with psycopg.connect(dsn) as connection:
            attach_segment_in_transaction(
                connection,
                namespace,
                task_id=task,
                segment_id=segment,
                predecessor_id=parent,
                reason=RolloverReason.RECOVERY,
            )

    return BindingStores(
        PostgresAgentTaskStore(dsn, deployment_namespace=namespace),
        PostgresEventStore(dsn, deployment_namespace=namespace),
        PostgresProjectionStore(dsn, deployment_namespace=namespace),
        PostgresWorkspaceProjectionStore(dsn, deployment_namespace=namespace),
        PostgresSessionHandoffStore(dsn, deployment_namespace=namespace),
        namespace,
        lambda: PostgresAgentTaskStore(dsn, deployment_namespace=namespace),
        fixture_attach,
    )


def forbidden(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("binding requested historical bodies/source repair")


def test_native_handoff_incremental_h_preserves_headers_and_cold_oracle(
    stores: BindingStores,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = prepare_native(stores, tmp_path)
    source_id, target = request.operation.source_session_id, request.operation.target_session_id
    task = TaskId(source_id)
    early = ready(stores.tasks, task)
    scope = scope_for(stores, early)
    resolve(stores.tasks, early, scope)
    publish(stores.tasks, early, scope)
    frozen = tuple(
        stores.tasks.read_event_projection_header(scope, n) for n in range(early.highwater + 1)
    )
    result = stores.handoffs.commit(request)  # Actual atomic parent/child/Task transaction.
    assert result.child_session_id == target
    run = ready(stores.tasks, task)
    receive = stores.tasks.read_handoff_receives(task, target, through_sequence=run.highwater)[0]
    committed = stores.tasks.read_latest_handoff_commit(
        task,
        source_id,
        request.operation.handoff_id,
        run.highwater + 1,
        through_sequence=run.highwater,
    )
    assert committed is not None
    if committed.source.task_sequence >= receive.source.task_sequence:
        # Bounded, body-free failure trace. No DSN, payload, environment or timestamps.
        trace = []
        for position in range(min(run.highwater + 1, 32)):
            source = stores.tasks.read_event_header(task, position)
            assert source is not None
            trace.append(
                (
                    position,
                    "parent" if source.segment_id == source_id else "child",
                    source.segment_sequence,
                    source.event_type.value,
                )
            )
        pytest.fail(
            f"native handoff canonical Task positions put receive before parent commit: "
            f"commit={committed.source.task_sequence}, receive={receive.source.task_sequence}; "
            f"canonical trace={trace}"
        )
    created_position = receive.source.task_sequence - 1
    prefix = stores.tasks.read_run_header(task, "run", through_sequence=created_position)
    cold = stores.cold()
    resolve(cold, prefix, scope)
    monkeypatch.setattr(cold, "read_events", forbidden)
    with pytest.raises(BindingResolutionPending) as pending:
        publish(cold, prefix, scope)
    assert pending.value.reason == "admission"
    assert cold.read_checkpoint_head(scope).through_sequence < created_position
    with pytest.raises(CheckpointNotReady):
        cold.read_event_projection_header(scope, created_position)
    append(
        stores, target, 4, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "child result"}
    )
    append(stores, source_id, 7, EventType.SESSION_TITLE_UPDATED, {"title": "late predecessor"})
    run = ready(stores.tasks, task)
    oracle = stores.tasks.read_events(task, -1)  # Test-only oracle before forbidding full reads.
    cold = stores.cold()
    monkeypatch.setattr(cold, "read_events", forbidden)
    resolve(cold, run, scope)
    publish(cold, run, scope)
    assert (
        tuple(cold.read_event_projection_header(scope, n) for n in range(early.highwater + 1))
        == frozen
    )
    created = cold.read_event_projection_header(scope, created_position)
    assert created is not None and created.projected
    compare_oracle(stores.cold(), oracle, run, scope)


@pytest.mark.parametrize("orphan_count", [257, 600])
def test_orphan_cold_cursor_progress_then_future_admission_without_source_repair(
    stores: BindingStores,
    monkeypatch: pytest.MonkeyPatch,
    orphan_count: int,
) -> None:
    parent = root(stores)
    task = TaskId(parent)
    descendant = child(stores, task, parent)
    append(
        stores,
        descendant,
        1,
        EventType.MODEL_RESPONSE_DELTA,
        {
            "attempt_number": 1,
            "model_call_id": "child",
            "delta_index": 0,
            "content_delta": "prefix",
        },
    )
    for sequence in range(2, orphan_count + 2):
        handoff(stores, descendant, sequence, EventType.SESSION_HANDOFF_RECEIVED, uuid4(), parent)
    run = ready(stores.tasks, task)
    scope = scope_for(stores, run)
    with monkeypatch.context() as scalar_only:
        scalar_only.setattr(stores.tasks, "read_events", forbidden)
        scalar_only.setattr(stores.tasks, "read_event_page", forbidden)
        scalar_only.setattr(stores.tasks, "backfill_event_positions", forbidden)
        scalar_only.setattr(stores.tasks, "backfill_replay_headers", forbidden)
        scalar_only.setattr(stores.tasks, "backfill_projection_sources", forbidden)
        head = advance_binding_resolution(stores.tasks, run, scope)
    assert 0 < head.through_sequence < 256
    cold = stores.cold()
    assert cold.read_checkpoint_head(binding_scope(scope)) == head
    positions: list[int] = []
    header_read = cold.read_event_header

    def seek(task_id: TaskId, position: int) -> TaskEventHeader | None:
        positions.append(position)
        return header_read(task_id, position)

    monkeypatch.setattr(cold, "read_event_header", seek)
    monkeypatch.setattr(cold, "read_events", forbidden)
    monkeypatch.setattr(cold, "backfill_event_positions", forbidden)
    monkeypatch.setattr(cold, "backfill_replay_headers", forbidden)
    monkeypatch.setattr(cold, "backfill_projection_sources", forbidden)
    resolve(cold, run, scope)
    assert positions and min(positions) > head.through_sequence
    assert cold.read_checkpoint_head(binding_scope(scope)).through_sequence == run.highwater
    with pytest.raises(BindingResolutionPending) as waiting:
        publish(cold, run, scope)
    assert waiting.value.reason == "admission"
    assert cold.read_checkpoint_head(scope).through_sequence == -1
    identity = uuid4()
    handoff(stores, parent, 2, EventType.SESSION_HANDOFF_COMMITTED, identity, descendant)
    handoff(
        stores, descendant, orphan_count + 2, EventType.SESSION_HANDOFF_RECEIVED, identity, parent
    )
    append(
        stores,
        descendant,
        orphan_count + 3,
        EventType.MODEL_RESPONSE_RECEIVED,
        {
            "model_call_id": "child",
            "assistant_message": "prefix final",
        },
    )
    run = ready(stores.tasks, task)
    oracle = stores.tasks.read_events(task, -1)
    cold = stores.cold()
    monkeypatch.setattr(cold, "read_events", forbidden)
    resolve(cold, run, scope)
    publish(cold, run, scope)
    compare_oracle(stores.cold(), oracle, run, scope)


def test_deep_chain_persists_direct_certificates_without_recursive_page_walk(
    stores: BindingStores,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = root(stores)
    task = TaskId(parent)
    for _depth in range(300):
        successor = child(stores, task, parent)
        identity = uuid4()
        handoff(stores, parent, 2, EventType.SESSION_HANDOFF_COMMITTED, identity, successor)
        handoff(stores, successor, 1, EventType.SESSION_HANDOFF_RECEIVED, identity, parent)
        parent = successor
    append(stores, parent, 2, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "leaf"})
    run = ready(stores.tasks, task)
    scope = scope_for(stores, run)
    oracle = stores.tasks.read_events(task, -1)
    head = advance_binding_resolution(stores.tasks, run, scope)
    cold = stores.cold()
    assert cold.read_checkpoint_head(binding_scope(scope)) == head
    monkeypatch.setattr(cold, "read_events", forbidden)
    monkeypatch.setattr(cold, "backfill_projection_sources", forbidden)
    resolve(cold, run, scope)
    publish(cold, run, scope)
    compare_oracle(stores.cold(), oracle, run, scope)


def test_closed_orphans_finish_as_negative_without_repeated_lookahead(
    stores: BindingStores,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = root(stores)
    task = TaskId(parent)
    descendant = child(stores, task, parent)
    for sequence in range(1, 258):
        handoff(stores, descendant, sequence, EventType.SESSION_HANDOFF_RECEIVED, uuid4(), parent)
    command(stores, parent, 2, "next")
    run = ready(stores.tasks, task)
    scope = scope_for(stores, run)
    oracle = stores.tasks.read_events(task, -1)
    assert run.stop is not None
    closed_through = run.stop - 1
    prefix = stores.tasks.read_run_header(task, "run", through_sequence=closed_through)
    assert prefix.stop is None  # Queue target deliberately excludes the next Run anchor.
    resolve(stores.tasks, prefix, scope)
    cold = stores.cold()
    monkeypatch.setattr(cold, "read_events", forbidden)
    monkeypatch.setattr(cold, "read_handoff_receives", forbidden)
    publish(cold, prefix, scope, closed_through=closed_through)
    for position in range(2, run.stop):
        header = cold.read_event_projection_header(scope, position)
        assert header is not None and not header.projected and not header.eligible
    scalar = cold.read_segment_checkpoint_before(scope, descendant, closed_through + 1)
    assert scalar.task_sequence == -1 and not scalar.started
    compare_oracle(stores.cold(), oracle, run, scope, end=closed_through)


def test_unproven_closure_cannot_publish_negative_membership(stores: BindingStores) -> None:
    parent = root(stores)
    task = TaskId(parent)
    descendant = child(stores, task, parent)
    captured = ready(stores.tasks, task)
    scope = scope_for(stores, captured)
    append(stores, descendant, 1, EventType.SESSION_TITLE_UPDATED, {"title": "not closure"})
    ready(stores.tasks, task)
    resolve(stores.tasks, captured, scope)
    with pytest.raises(CheckpointConflict, match="closure"):
        publish(stores.cold(), captured, scope, closed_through=captured.highwater)
    assert stores.tasks.read_checkpoint_head(scope).through_sequence == -1


def test_cold_old_negative_cannot_warm_late_pair_before_receive(stores: BindingStores) -> None:
    parent = root(stores)
    task = TaskId(parent)
    descendant = child(stores, task, parent)
    early = ready(stores.tasks, task)
    scope = scope_for(stores, early)
    identity = AgUiRunIdentity(session_id=parent, thread_id=str(task), run_id="run")
    page = stores.tasks.read_event_page(task, -1, through_sequence=early.highwater)
    decisions = []
    for entry in page.events:
        source = stores.tasks.read_event_header(task, entry.task_sequence)
        assert source is not None
        selected = entry.segment_id == parent
        decisions.append(
            ProjectionEventPlan(source, selected, selected and entry.task_sequence >= early.start)
        )
    transition = AgUiCheckpointMaterializer(stores.tasks).prepare_page(
        page, ProjectionPagePlan(early, tuple(decisions)), scope, identity
    )
    assert transition is not None
    old = stores.tasks.commit_projection_page(transition)
    frozen = tuple(
        stores.tasks.read_event_projection_header(scope, n) for n in range(early.highwater + 1)
    )
    handoff_id = uuid4()
    handoff(stores, parent, 2, EventType.SESSION_HANDOFF_COMMITTED, handoff_id, descendant)
    append(stores, descendant, 1, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "late"})
    handoff(stores, descendant, 2, EventType.SESSION_HANDOFF_RECEIVED, handoff_id, parent)
    run = ready(stores.tasks, task)
    cold = stores.cold()
    resolve(cold, run, scope)
    # This Page ends before receive. Negative output coverage is authoritative
    # even though the separate, newer binding ledger now has a positive certificate.
    page = cold.read_event_page(task, early.highwater, limit=2, through_sequence=run.highwater)
    assert page.events[-1].event.event_type is EventType.MODEL_RESPONSE_RECEIVED
    plan = build_projection_page_plan(cold, page, run, scope, identity)
    with pytest.raises(CheckpointConflict, match="retroactively"):
        AgUiCheckpointMaterializer(cold).prepare_page(page, plan, scope, identity)
    assert cold.read_checkpoint_head(scope) == old
    assert (
        tuple(cold.read_event_projection_header(scope, n) for n in range(early.highwater + 1))
        == frozen
    )


def test_foreign_scopes_cannot_write_binding_or_output_heads(stores: BindingStores) -> None:
    parent = root(stores)
    run = ready(stores.tasks, TaskId(parent))
    scope = scope_for(stores, run)
    page = stores.tasks.read_event_page(run.task_id, -1, through_sequence=run.highwater)
    identity = AgUiRunIdentity(session_id=parent, thread_id=str(run.task_id), run_id=run.run_id)
    for forged in (
        replace(scope, namespace="foreign-binding-scope"),
        replace(scope, task_id=TaskId(uuid4())),
        replace(scope, anchor_event_id=EventId(uuid4())),
        replace(scope, projector_version="unsupported"),
    ):
        with pytest.raises(CheckpointConflict):
            advance_binding_resolution(stores.tasks, run, forged)
        with pytest.raises((CheckpointConflict, AgUiProjectionError)):
            build_projection_page_plan(stores.tasks, page, run, forged, identity)
    assert stores.tasks.read_checkpoint_head(scope).through_sequence == -1
    assert stores.tasks.read_checkpoint_head(binding_scope(scope)).through_sequence == -1


def test_closed_target_must_equal_h_and_verify_same_anchor(
    stores: BindingStores, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = root(stores)
    task = TaskId(parent)
    early = ready(stores.tasks, task)
    scope = scope_for(stores, early)
    identity = AgUiRunIdentity(session_id=parent, thread_id=str(task), run_id=early.run_id)
    command(stores, parent, 2, "next")
    confirmed = ready(stores.tasks, task)
    assert confirmed.stop == early.highwater + 1 and confirmed.anchor is not None
    page = stores.tasks.read_event_page(task, -1, through_sequence=early.highwater)
    for invalid in (True, early.highwater - 1, confirmed.highwater):
        with pytest.raises(CheckpointConflict, match="closure"):
            build_projection_page_plan(
                stores.tasks, page, early, scope, identity, closed_through=invalid
            )

    def foreign_anchor(
        task_id: TaskId, run_id: str, *, through_sequence: int | None = None
    ) -> TaskRunHeader:
        assert task_id == task and run_id == early.run_id
        assert through_sequence == early.highwater + 1
        assert confirmed.anchor is not None
        return replace(confirmed, anchor=replace(confirmed.anchor, event_id=EventId(uuid4())))

    monkeypatch.setattr(stores.tasks, "read_run_header", foreign_anchor)
    with pytest.raises(CheckpointConflict, match="closure"):
        build_projection_page_plan(
            stores.tasks, page, early, scope, identity, closed_through=early.highwater
        )
    assert stores.tasks.read_checkpoint_head(scope).through_sequence == -1
