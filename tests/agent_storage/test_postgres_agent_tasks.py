from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.ports import WorkerMutationAuthority
from agent_storage import (
    PostgresAgentTaskConflictError,
    PostgresAgentTaskStore,
    PostgresEventStore,
    PostgresLeaseStore,
    PostgresProjectionStore,
    apply_postgres_migrations,
    attach_segment_in_transaction,
    bootstrap_control_plane_epoch,
)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def task_namespace(postgres_dsn: str) -> Generator[str]:
    namespace = f"task-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
    yield namespace
    _delete_namespace(postgres_dsn, namespace)


def test_reads_do_not_implicitly_build_task_index(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    task_id = TaskId(root)
    store = _store(postgres_dsn, task_namespace)

    assert store.get_task(task_id) is None
    assert store.list_tasks(limit=10) == ()
    assert store.segments(task_id) == ()
    assert store.active_segment(task_id) is None
    assert store.read_events(task_id, -1) == ()
    assert not store.is_internal_segment(root)
    assert store.task_id_for_session(root) is None

    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM agent_tasks WHERE deployment_namespace = %s",
            (task_namespace,),
        ).fetchone() == (0,)


def test_direct_postgres_rollover_requires_worker_authority(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    child = _seed_session(postgres_dsn, task_namespace, tmp_path / "child", "Child")
    store = _store(postgres_dsn, task_namespace)
    task = store.ensure_for_session(root)

    with pytest.raises(PostgresAgentTaskConflictError, match="WorkerMutationAuthority"):
        store.attach_segment(
            task.task_id,
            child,
            predecessor_id=root,
            reason=RolloverReason.RECOVERY,
        )

    assert store.active_segment(task.task_id) == root
    assert [item.session_id for item in store.segments(task.task_id)] == [root]


def test_explicit_rebuild_is_idempotent_and_task_event_order_is_unique(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    child = _seed_session(postgres_dsn, task_namespace, tmp_path / "child", "Child")
    _append_handoff_events(postgres_dsn, task_namespace, root=root, child=child)
    store = _store(postgres_dsn, task_namespace)

    first = store.ensure_for_session(child)
    before = store.read_events(first.task_id, -1)
    assert store.rebuild_all() == 1
    assert store.rebuild_all() == 1
    after = store.read_events(first.task_id, -1)

    assert after == before
    assert first.task_id == TaskId(root)
    segments = store.segments(first.task_id)
    assert [item.session_id for item in segments] == [root, child]
    assert segments[1].predecessor_id == root
    assert segments[1].segment_index == 1
    assert segments[1].rollover_reason is RolloverReason.RECOVERY
    assert [item.task_sequence for item in after] == list(range(len(after)))
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            """
            SELECT count(*), count(DISTINCT task_sequence), count(DISTINCT event_id)
            FROM task_event_index
            WHERE deployment_namespace = %s AND task_id = %s
            """,
            (task_namespace, first.task_id),
        ).fetchone() == (len(after), len(after), len(after))


def test_concurrent_rollover_has_one_winner_and_indexes_child_events(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    children = (
        _seed_session(postgres_dsn, task_namespace, tmp_path / "a", "A"),
        _seed_session(postgres_dsn, task_namespace, tmp_path / "b", "B"),
    )
    task = _store(postgres_dsn, task_namespace).ensure_for_session(root)
    authority = _worker_authority(postgres_dsn, task_namespace, root)

    def rollover(child: SessionId) -> object:
        try:
            return _store(postgres_dsn, task_namespace).attach_segment_for_worker(
                task.task_id,
                child,
                predecessor_id=root,
                reason=RolloverReason.TERMINAL_FOLLOW_UP,
                authority=authority,
            )
        except PostgresAgentTaskConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(rollover, children))

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, Exception) for result in results) == 1
    store = _store(postgres_dsn, task_namespace)
    segments = store.segments(task.task_id)
    assert len(segments) == 2
    assert store.active_segment(task.task_id) in children
    events = store.read_events(task.task_id, -1)
    assert [item.task_sequence for item in events] == list(range(len(events)))
    assert {item.segment_id for item in events} == {root, segments[-1].session_id}


def test_rebuild_rejects_noncanonical_membership_without_renumbering_published_events(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    stale = _seed_session(postgres_dsn, task_namespace, tmp_path / "stale", "Stale")
    canonical = _seed_session(postgres_dsn, task_namespace, tmp_path / "canonical", "Canonical")
    store = _store(postgres_dsn, task_namespace)
    task = store.ensure_for_session(root)
    store.attach_segment_for_worker(
        task.task_id,
        stale,
        predecessor_id=root,
        reason=RolloverReason.AGENT_HINT,
        authority=_worker_authority(postgres_dsn, task_namespace, root),
    )
    _append_handoff_events(postgres_dsn, task_namespace, root=root, child=canonical)

    published = store.read_events(task.task_id, -1)
    with pytest.raises(PostgresAgentTaskConflictError, match="membership cannot be rewritten"):
        store.ensure_for_session(canonical)
    assert store.read_events(task.task_id, -1) == published
    assert store.active_segment(task.task_id) == stale
    assert [item.session_id for item in store.segments(task.task_id)] == [root, stale]
    assert [item.task_sequence for item in published] == list(range(len(published)))


@pytest.mark.parametrize("fault", ["checksum", "artifact", "orphan"])
def test_rebuild_rejects_unpaired_handoff_without_partial_index(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
    fault: str,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    child = _seed_session(postgres_dsn, task_namespace, tmp_path / "child", "Child")
    _append_handoff_events(
        postgres_dsn,
        task_namespace,
        root=root,
        child=child,
        mismatched_checksum=fault == "checksum",
        mismatched_artifact=fault == "artifact",
        omit_committed=fault == "orphan",
    )

    with pytest.raises(PostgresAgentTaskConflictError, match="does not match"):
        _store(postgres_dsn, task_namespace).ensure_for_session(child)

    assert _store(postgres_dsn, task_namespace).get_task(TaskId(root)) is None


def test_rebuild_rejects_ambiguous_received_handoff_lineage(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    roots = (
        _seed_session(postgres_dsn, task_namespace, tmp_path / "root-a", "Root A"),
        _seed_session(postgres_dsn, task_namespace, tmp_path / "root-b", "Root B"),
    )
    child = _seed_session(postgres_dsn, task_namespace, tmp_path / "child", "Child")
    for root in roots:
        _append_handoff_events(postgres_dsn, task_namespace, root=root, child=child)

    with pytest.raises(PostgresAgentTaskConflictError, match="ambiguous"):
        _store(postgres_dsn, task_namespace).ensure_for_session(child)

    assert all(
        _store(postgres_dsn, task_namespace).get_task(TaskId(root)) is None for root in roots
    )


def test_external_handoff_reason_matches_sqlite_rollover_mapping(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    child = _seed_session(postgres_dsn, task_namespace, tmp_path / "child", "Child")
    _append_handoff_events(
        postgres_dsn,
        task_namespace,
        root=root,
        child=child,
        reason="operator_handoff",
    )

    task = _store(postgres_dsn, task_namespace).ensure_for_session(child)

    assert _store(postgres_dsn, task_namespace).segments(task.task_id)[1].rollover_reason is (
        RolloverReason.CONTEXT_PRESSURE
    )


def test_rebuild_and_rollover_share_one_task_transaction_lock(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    child = _seed_session(postgres_dsn, task_namespace, tmp_path / "child", "Child")
    store = _store(postgres_dsn, task_namespace)
    task = store.ensure_for_session(root)
    authority = _worker_authority(postgres_dsn, task_namespace, root)

    def rebuild() -> object:
        return _store(postgres_dsn, task_namespace).ensure_for_session(root)

    def rollover() -> object:
        return _store(postgres_dsn, task_namespace).attach_segment_for_worker(
            task.task_id,
            child,
            predecessor_id=root,
            reason=RolloverReason.RECOVERY,
            authority=authority,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.submit(action) for action in (rebuild, rollover))
        assert all(future.result() is not None for future in results)

    segments = store.segments(task.task_id)
    assert [item.segment_index for item in segments] == list(range(len(segments)))
    assert store.active_segment(task.task_id) == segments[-1].session_id
    events = store.read_events(task.task_id, -1)
    assert [item.task_sequence for item in events] == list(range(len(events)))


@pytest.mark.parametrize("invalid", ["fence", "namespace", "session", "stream"])
def test_worker_rollover_rejects_invalid_authority_without_writes(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
    invalid: str,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    child = _seed_session(postgres_dsn, task_namespace, tmp_path / "child", "Child")
    store = _store(postgres_dsn, task_namespace)
    task = store.ensure_for_session(root)
    authority = _worker_authority(postgres_dsn, task_namespace, root)
    if invalid == "fence":
        authority = authority.model_copy(
            update={
                "lease_fence": authority.lease_fence.model_copy(
                    update={"fencing_token": authority.lease_fence.fencing_token + 1}
                )
            }
        )
    elif invalid == "namespace":
        authority = authority.model_copy(update={"deployment_namespace": "other-namespace"})
    elif invalid == "session":
        authority = authority.model_copy(update={"session_id": child})
    else:
        authority = authority.model_copy(
            update={"expected_stream_revision": authority.expected_stream_revision + 1}
        )

    expected_error = LeaseLostError if invalid != "stream" else PostgresAgentTaskConflictError
    with pytest.raises(expected_error):
        store.attach_segment_for_worker(
            task.task_id,
            child,
            predecessor_id=root,
            reason=RolloverReason.RECOVERY,
            authority=authority,
        )

    assert store.active_segment(task.task_id) == root
    assert [item.session_id for item in store.segments(task.task_id)] == [root]


def test_connection_scoped_rollover_rolls_back_with_caller_transaction(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    child = _seed_session(postgres_dsn, task_namespace, tmp_path / "child", "Child")
    task = _store(postgres_dsn, task_namespace).ensure_for_session(root)

    with pytest.raises(RuntimeError, match="fault after Task update"):
        with psycopg.connect(postgres_dsn) as connection:
            attach_segment_in_transaction(
                connection,
                task_namespace,
                task_id=task.task_id,
                segment_id=child,
                predecessor_id=root,
                reason=RolloverReason.RECOVERY,
            )
            raise RuntimeError("fault after Task update")

    store = _store(postgres_dsn, task_namespace)
    assert store.active_segment(task.task_id) == root
    assert [item.session_id for item in store.segments(task.task_id)] == [root]


def test_same_task_identity_is_isolated_by_namespace(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    other = f"{task_namespace}-other"
    root, events = _bootstrap(tmp_path / "shared", "Shared")
    try:
        for namespace in (task_namespace, other):
            event_store = PostgresEventStore(postgres_dsn, deployment_namespace=namespace)
            for event in events:
                event_store.append(event)
            PostgresProjectionStore(
                postgres_dsn,
                deployment_namespace=namespace,
            ).save_session(rebuild_session(list(events)))

        first = _store(postgres_dsn, task_namespace).ensure_for_session(root)
        second = _store(postgres_dsn, other).ensure_for_session(root)

        assert first.task_id == second.task_id
        assert first.namespace == task_namespace
        assert second.namespace == other
        assert _store(postgres_dsn, task_namespace).list_tasks(limit=10) == (first,)
        assert _store(postgres_dsn, other).list_tasks(limit=10) == (second,)
    finally:
        _delete_namespace(postgres_dsn, other)


def test_late_predecessor_append_and_index_repair_keep_source_positions(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    child = _seed_session(postgres_dsn, task_namespace, tmp_path / "child", "Child")
    store = _store(postgres_dsn, task_namespace)
    task = store.ensure_for_session(root)
    store.attach_segment_for_worker(
        task.task_id,
        child,
        predecessor_id=root,
        reason=RolloverReason.RECOVERY,
        authority=_worker_authority(postgres_dsn, task_namespace, root),
    )
    before = store.read_events(task.task_id, -1)
    history = PostgresEventStore(postgres_dsn, deployment_namespace=task_namespace)
    late = SessionEvent.create(
        session_id=root,
        sequence=len(history.list_for_session(root)),
        event_type=EventType.SESSION_TITLE_UPDATED,
        actor=EventActor.SYSTEM,
        payload={"title": "Late title"},
        idempotency_key="late-title",
    )
    history.append(late)
    after = store.read_events(task.task_id, -1)
    assert after[:-1] == before and after[-1].event == late
    assert after[-1].task_sequence == len(before)
    history.append(late)
    assert store.read_events(task.task_id, -1) == after
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "DELETE FROM task_event_index WHERE deployment_namespace=%s AND task_sequence=1",
            (task_namespace,),
        )
    assert store.read_events(task.task_id, -1) == after
    assert store.backfill_event_positions(task.task_id)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT task_sequence FROM task_event_index WHERE deployment_namespace=%s "
            "ORDER BY task_sequence",
            (task_namespace,),
        ).fetchall() == [(index,) for index in range(len(after))]


@pytest.mark.parametrize("column", ["task_id", "task_sequence", "sequence"])
def test_published_source_coordinates_cannot_be_reassigned(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
    column: str,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path, "Root")
    store = _store(postgres_dsn, task_namespace)
    task = store.ensure_for_session(root)
    before = store.read_events(task.task_id, -1)
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable"):
        with psycopg.connect(postgres_dsn) as connection:
            value = uuid4() if column == "task_id" else 9000
            connection.execute(
                f"UPDATE session_events SET {column}=%s "
                "WHERE deployment_namespace=%s AND sequence=0",
                (value, task_namespace),
            )
    assert store.read_events(task.task_id, -1) == before


def test_conflicting_index_position_is_not_silently_rebuilt(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path, "Root")
    store = _store(postgres_dsn, task_namespace)
    task = store.ensure_for_session(root)
    before = store.read_events(task.task_id, -1)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE task_event_index SET task_sequence=9000 "
            "WHERE deployment_namespace=%s AND task_sequence=0",
            (task_namespace,),
        )
    with pytest.raises(PostgresAgentTaskConflictError, match="conflicts with source"):
        store.backfill_event_positions(task.task_id)
    assert store.read_events(task.task_id, -1) == before


def test_rollover_rejects_foreign_assigned_child_before_membership(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    child = _seed_session(postgres_dsn, task_namespace, tmp_path / "child", "Child")
    store = _store(postgres_dsn, task_namespace)
    task = store.ensure_for_session(root)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """UPDATE session_events SET task_id=%s,task_sequence=sequence
               WHERE deployment_namespace=%s AND session_id=%s""",
            (uuid4(), task_namespace, child),
        )
    with (
        psycopg.connect(postgres_dsn) as connection,
        pytest.raises(PostgresAgentTaskConflictError, match="another Task"),
    ):
        attach_segment_in_transaction(
            connection,
            task_namespace,
            task_id=task.task_id,
            segment_id=child,
            predecessor_id=root,
            reason=RolloverReason.RECOVERY,
        )
    assert store.active_segment(task.task_id) == root
    assert [member.session_id for member in store.segments(task.task_id)] == [root]


def test_rollover_does_not_publish_a_partially_adopted_large_child(
    postgres_dsn: str,
    task_namespace: str,
    tmp_path: Path,
) -> None:
    root = _seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    child = _seed_session(postgres_dsn, task_namespace, tmp_path / "child", "Child")
    history = PostgresEventStore(postgres_dsn, deployment_namespace=task_namespace)
    for sequence in range(len(history.list_for_session(child)), 257):
        history.append(
            SessionEvent.create(
                session_id=child,
                sequence=sequence,
                actor=EventActor.SYSTEM,
                event_type=EventType.SESSION_TITLE_UPDATED,
                payload={"title": "Child"},
            )
        )
    store = _store(postgres_dsn, task_namespace)
    task = store.ensure_for_session(root)
    frozen = store.read_event_page(task.task_id, -1).events
    with psycopg.connect(postgres_dsn) as connection:
        attach_segment_in_transaction(
            connection,
            task_namespace,
            task_id=task.task_id,
            segment_id=child,
            predecessor_id=root,
            reason=RolloverReason.RECOVERY,
        )
    assert store.active_segment(task.task_id) == child
    assert [member.session_id for member in store.segments(task.task_id)] == [root, child]
    with pytest.raises(PostgresAgentTaskConflictError, match="explicit backfill"):
        store.read_event_page(task.task_id, -1)
    assert store.backfill_event_positions(task.task_id)
    assert store.read_event_page(task.task_id, -1).events[: len(frozen)] == frozen
    tail = store.read_event_page(task.task_id, len(frozen) + 255).events
    assert [(item.task_sequence, item.segment_sequence) for item in tail] == [
        (len(frozen) + 256, 256)
    ]


def _seed_session(
    dsn: str,
    namespace: str,
    workspace: Path,
    title: str,
) -> SessionId:
    session_id, events = _bootstrap(workspace, title)
    store = PostgresEventStore(dsn, deployment_namespace=namespace)
    for event in events:
        store.append(event)
    PostgresProjectionStore(dsn, deployment_namespace=namespace).save_session(
        rebuild_session(list(events))
    )
    return session_id


def _bootstrap(workspace: Path, title: str) -> tuple[SessionId, tuple[SessionEvent, ...]]:
    result = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title=title,
            user_input=title,
            workspace_root=workspace,
            policy_profile="workspace_write",
            tool_profile=ToolProfile.CODING,
            network_profile="none",
        )
    )
    return result.session.session_id, result.events


def _store(dsn: str, namespace: str) -> PostgresAgentTaskStore:
    return PostgresAgentTaskStore(dsn, deployment_namespace=namespace)


def _worker_authority(
    dsn: str,
    namespace: str,
    session_id: SessionId,
) -> WorkerMutationAuthority:
    lease = PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        session_id,
        owner_instance_id=f"task-test-{uuid4()}",
        ttl=timedelta(minutes=5),
    )
    with psycopg.connect(dsn) as connection:
        stream = connection.execute(
            """SELECT current_version FROM session_streams
               WHERE deployment_namespace = %s AND session_id = %s""",
            (namespace, session_id),
        ).fetchone()
    assert stream is not None
    return WorkerMutationAuthority(
        deployment_namespace=namespace,
        session_id=session_id,
        lease_fence=lease.fence,
        expected_stream_revision=stream[0],
    )


def _append_handoff_events(
    dsn: str,
    namespace: str,
    *,
    root: SessionId,
    child: SessionId,
    mismatched_checksum: bool = False,
    mismatched_artifact: bool = False,
    omit_committed: bool = False,
    reason: str = "internal_recovery",
) -> None:
    events = PostgresEventStore(dsn, deployment_namespace=namespace)
    handoff_id = str(uuid4())
    root_history = events.list_for_session(root)
    committed = SessionEvent.create(
        session_id=root,
        sequence=len(root_history),
        event_type=EventType.SESSION_HANDOFF_COMMITTED,
        actor=EventActor.SYSTEM,
        created_at=datetime.now(UTC),
        payload={
            "handoff_id": handoff_id,
            "target_session_id": str(child),
            "reason": reason,
            "target_stage_index": 1,
            "source_event_range": {
                "start_sequence": 0,
                "end_sequence": len(root_history) - 1,
            },
            "source_event_hash": "source-hash",
            "artifact_id": "different-artifact" if mismatched_artifact else "artifact",
            "checksum": "different-checksum" if mismatched_checksum else "checksum",
            "idempotency_key_hash": "idempotency-hash",
        },
    )
    if not omit_committed:
        events.append(committed)
        PostgresProjectionStore(dsn, deployment_namespace=namespace).save_session(
            rebuild_session([*root_history, committed])
        )
    child_history = events.list_for_session(child)
    received = SessionEvent.create(
        session_id=child,
        sequence=len(child_history),
        event_type=EventType.SESSION_HANDOFF_RECEIVED,
        actor=EventActor.SYSTEM,
        created_at=datetime.now(UTC),
        payload={
            "parent_session_id": str(root),
            "root_session_id": str(root),
            "handoff_id": handoff_id,
            "stage_index": 1,
            "artifact_id": "artifact",
            "checksum": "checksum",
        },
    )
    events.append(received)
    PostgresProjectionStore(dsn, deployment_namespace=namespace).save_session(
        rebuild_session([*child_history, received])
    )


def _delete_namespace(dsn: str, namespace: str) -> None:
    with psycopg.connect(dsn) as connection:
        # Only this test-owned namespace is decommissioned; source immutability
        # remains enforced until Task ownership has been explicitly removed.
        connection.execute(
            "SELECT set_config('zebra.task_source_cleanup_namespace',%s,true)",
            (namespace,),
        )
        for table in (
            "worker_leases",
            "agent_tasks",
            "task_event_index",
            "execution_segments",
            "session_projections",
            "session_events",
            "session_streams",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE deployment_namespace = %s",
                (namespace,),
            )
