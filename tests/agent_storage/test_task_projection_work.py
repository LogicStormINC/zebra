"""One behavior contract against SQLite and isolated real PostgreSQL."""

import threading
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from agent_core.domain.identifiers import EventId, TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_core.ports.task_projection_work import TaskProjectionWorkPort

from tests.agent_storage.projection_work_test_support import QueueFixture
from tests.agent_storage.test_postgres_scalar_task_replay_headers import scratch as scratch
from tests.agent_storage.test_projection_work_native import failure_count, transient_failures


@pytest.fixture(params=["sqlite", "postgres"])
def queue(request, tmp_path):
    return QueueFixture(
        request.param,
        tmp_path,
        request.getfixturevalue("scratch") if request.param == "postgres" else None,
    )


def active(queue):
    queue.install()
    store: TaskProjectionWorkPort = queue.store()
    store.enable_projection_work()
    return store


def test_inert_enable_legacy_discovery_and_restart(queue):
    queue.append(0)
    queue.install()
    assert queue.table_counts() == (0, 0, 0, 0)
    store = queue.store()
    assert store.read_pending_projection_work() == ()
    assert queue.table_counts() == (0, 0, 0, 0)
    store.enable_projection_work()
    assert queue.table_counts() == (1, 0, 0, 0)
    queue.append(1, body='{"ok":true}')
    assert store.read_pending_projection_work() == ()
    (repair,) = queue.store().read_projection_work_repairs()
    assert (repair.after_sequence, repair.wanted_through) == (-1, 1)
    assert not store.repair_projection_work(queue.task).needs_repair
    (work,) = queue.store().read_pending_projection_work()
    assert (work.anchor_sequence, work.requested_through, work.after_sequence) == (0, 1, -1)
    assert queue.table_counts()[-1] == 0  # Reading never creates a checkpoint.


def test_native_run_stop_control_internal_continuation_and_no_reopen(queue):
    store = active(queue)
    queue.append(0, run="one")
    for n, kwargs in enumerate(
        (
            dict(kind="cancel", run="control"),
            dict(kind="resume", run=None, actor="harness", key="child-wakeup:"),
            dict(kind="resume", run=None, actor="harness", key="client-effect-resume:"),
            dict(body='{"receipt":"done"}'),
        ),
        1,
    ):
        queue.append(n, **kwargs)
    (first,) = store.read_pending_projection_work()
    assert first.requested_through == 4
    assert len(queue.work_rows()) == 1
    queue.append(5, kind="message", run="two")
    rows = queue.work_rows()
    assert [(r["requested_through"], r["closed_through"]) for r in rows] == [(4, 4), (5, None)]
    old = next(w for w in store.read_pending_projection_work() if w.run_id == "one")
    queue.set_head(old)
    assert store.complete_projection_work(old, expected_through=4)
    queue.append(6, body='{"receipt":"later"}')
    with queue.connect() as connection:
        queue.execute(
            connection,
            "UPDATE session_events SET task_sequence=task_sequence WHERE task_sequence=0",
        )
    assert not store.repair_projection_work(queue.task).needs_repair
    rows = queue.work_rows()
    assert (rows[0]["pending"], rows[0]["closed_through"], rows[0]["revision"]) == (
        0,
        4,
        old.revision,
    )
    (second,) = queue.store().read_pending_projection_work()
    assert second.run_id == "two" and second.requested_through == 6


def test_unassigned_native_row_only_wakes_after_coordinates(queue):
    store = active(queue)
    queue.append(0, assigned=False)
    assert store.read_pending_projection_work() == ()
    with queue.connect() as connection:
        queue.execute(
            connection,
            "UPDATE session_events SET task_id=?,task_sequence=0 WHERE sequence=0",
            (str(queue.task),),
        )
        queue.execute(connection, "UPDATE agent_tasks SET next_event_sequence=1")
    (work,) = store.read_pending_projection_work()
    assert work.anchor_sequence == 0


def test_null_public_run_stops_previous_without_inventing_identity(queue):
    store = active(queue)
    queue.append(0)
    queue.append(1, kind="message", run=None)
    queue.append(2, body='{"receipt":"not a new run"}')
    (work,) = store.read_pending_projection_work()
    assert (work.requested_through, work.closed_through) == (0, 0)
    assert len(queue.work_rows()) == 1


def test_head_and_revision_cas_append_before_and_after_ack(queue):
    store = active(queue)
    queue.append(0)
    (stale,) = store.read_pending_projection_work()
    assert not store.complete_projection_work(stale, expected_through=0)
    queue.set_head(stale)
    queue.append(1, body='{"receipt":"new"}')
    assert not store.complete_projection_work(stale, expected_through=0)
    (work,) = queue.store().read_pending_projection_work()
    assert work.after_sequence == 0 and work.requested_through == 1
    assert not store.complete_projection_work(work, expected_through=1)
    queue.set_head(work)
    assert store.complete_projection_work(work, expected_through=1)
    assert store.read_pending_projection_work() == ()
    queue.append(2, body='{"receipt":"after ACK"}')
    (wake,) = queue.store().read_pending_projection_work()
    assert wake.requested_through == 2 and wake.revision > work.revision


def test_simultaneous_append_ack_never_loses_wake(queue):
    store = active(queue)
    queue.append(0)
    (work,) = store.read_pending_projection_work()
    queue.set_head(work)
    barrier = threading.Barrier(2)
    results, errors = [], []

    def acknowledge():
        try:
            barrier.wait(timeout=5)
            results.append(store.complete_projection_work(work, expected_through=0))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=acknowledge)
    thread.start()
    barrier.wait(timeout=5)
    queue.append(1, body='{"receipt":"concurrent"}')
    thread.join(timeout=5)
    assert not thread.is_alive() and not errors
    assert len(results) == 1
    (pending,) = queue.store().read_pending_projection_work()
    assert pending.requested_through == 1


def test_duplicate_builders_only_one_ack_can_clear(queue):
    store = active(queue)
    queue.append(0)
    (work,) = store.read_pending_projection_work()
    queue.set_head(work)
    assert store.complete_projection_work(work, expected_through=0)
    assert not queue.store().complete_projection_work(work, expected_through=0)


def test_forged_namespace_version_anchor_and_run_rejected(queue):
    store = active(queue)
    queue.append(0)
    (work,) = store.read_pending_projection_work()
    for scope in (
        replace(work.scope, namespace="other"),
        replace(work.scope, projector_version="other"),
        replace(work.scope, anchor_event_id=EventId(uuid4())),
    ):
        with pytest.raises(CheckpointConflict):
            store.complete_projection_work(replace(work, scope=scope), expected_through=0)
    with pytest.raises(CheckpointConflict):
        store.complete_projection_work(replace(work, run_id="forged"), expected_through=0)
    with pytest.raises(CheckpointConflict):
        store.complete_projection_work(work, expected_through=1)
    with pytest.raises(CheckpointConflict):
        queue.store(namespace="other").repair_projection_work(queue.task)
    with pytest.raises(CheckpointConflict):
        store.repair_projection_work(TaskId(UUID(int=42)))
    with pytest.raises(CheckpointConflict):
        store.read_pending_projection_work(after_scope=replace(work.scope, namespace="other"))


def test_bounded_roundrobin_and_projector_fanout(queue):
    store = active(queue)
    for n in range(40):
        queue.append(n, run=f"run-{n}")
    first = store.read_pending_projection_work()
    assert len(first) == 32
    rest = store.read_pending_projection_work(after_scope=first[-1].scope)
    assert len(rest) == 8
    assert store.read_pending_projection_work(after_scope=rest[-1].scope) == ()
    for v in range(5):
        queue.store(version=f"other-{v}").enable_projection_work()
    with pytest.raises(ValueError, match="budget"):
        queue.store(version="seventh").enable_projection_work()
    queue.append(40, body='{"receipt":"fanout"}')
    assert len(store.read_projection_work_repairs()) == 0
    assert len(queue.store(version="other-0").read_projection_work_repairs()) == 1
    store.disable_projection_work()
    assert store.read_pending_projection_work() == ()
    queue.store(version="seventh").enable_projection_work()
    for invalid in (0, 33, True, -1):
        with pytest.raises(ValueError):
            store.read_pending_projection_work(limit=invalid)


def test_scalar_fanout_receipt_and_next_anchor_are_route_scoped(queue):
    active(queue)
    versions = ["ag-ui-v1", "other-0", "other-1", "other-2"]
    for version in versions[1:]:
        queue.store(version=version).enable_projection_work()
    other_task = UUID(int=queue.task.int ^ 1)
    namespace_column = "namespace" if queue.backend == "sqlite" else "deployment_namespace"
    with queue.connect() as connection:
        queue.execute(
            connection,
            f"INSERT INTO agent_tasks(task_id,{namespace_column},next_event_sequence,"
            "event_position_state) VALUES (?,?,0,'ready')",
            (str(other_task), queue.namespace),
        )
        other_before = [dict(row) for row in queue.execute(
            connection, "SELECT * FROM task_projection_work_routes WHERE task_id=? "
            "ORDER BY projector_version", (str(other_task),),
        ).fetchall()]
    queue.append(0, run="one")
    queue.append(1, body='{"receipt":"fanout"}')
    queue.append(2, kind="message", run="two")
    assert sorted(
        (row["projector_version"], row["anchor_sequence"], row["requested_through"],
         row["closed_through"]) for row in queue.work_rows()
    ) == sorted((version, anchor, through, closed) for version in versions
                for anchor, through, closed in ((0, 1, 1), (2, 2, None)))
    with queue.connect() as connection:
        assert [dict(row) for row in queue.execute(
            connection, "SELECT * FROM task_projection_work_routes WHERE task_id=? "
            "ORDER BY projector_version", (str(other_task),),
        ).fetchall()] == other_before


def test_persistent_finite_defer_and_explicit_retry(queue, monkeypatch):
    store = active(queue)
    queue.append(0)
    (work,) = store.read_pending_projection_work()
    monkeypatch.setattr("agent_storage.projection_work.time.time", lambda: 1000.0)
    assert store.defer_projection_work(work, problem_code="not_ready", retry_after_seconds=1)
    assert store.read_pending_projection_work() == ()
    problem = queue.store().read_projection_work_problem(work.scope)
    assert (problem.code, problem.attempts, problem.retry_at) == ("not_ready", 1, 1001)
    assert queue.store().retry_due_projection_work() == 0
    queue.append(1, body='{"receipt":"must preserve deferred wake"}')
    assert queue.store().read_pending_projection_work() == ()
    for failure in range(2, 9):
        monkeypatch.setattr(
            "agent_storage.projection_work.time.time", lambda failure=failure: 1000.0 + failure * 2
        )
        assert queue.store().retry_due_projection_work() == 1
        (work,) = queue.store().read_pending_projection_work()
        assert work.requested_through == 1
        assert store.defer_projection_work(work, problem_code="not_ready", retry_after_seconds=1)
    problem = store.read_projection_work_problem(work.scope)
    assert problem.attempts == 8 and problem.retry_at is None
    assert queue.store().retry_due_projection_work() == 0
    queue.append(2, body='{"receipt":"exhausted fault must not auto-retry"}')
    assert queue.store().read_pending_projection_work() == ()
    assert queue.store().read_projection_work_problem(work.scope).attempts == 8
    assert not store.retry_projection_work(work.scope, expected_attempt=7)
    assert store.retry_projection_work(work.scope, expected_attempt=8)
    (work,) = store.read_pending_projection_work()
    assert store.defer_projection_work(work, problem_code="integrity")
    assert store.read_projection_work_problem(work.scope).retry_at is None
    queue.append(3, kind="message", run="next")
    assert store.read_projection_work_problem(work.scope).code == "integrity"
    with pytest.raises(ValueError):
        store.defer_projection_work(work, problem_code="integrity", retry_after_seconds=1)


def test_explicit_repair_row_budget_progress_restart_and_gaps(queue):
    for n in range(600):
        queue.append(n, body="{}" if n else None)
    store = active(queue)
    assert store.read_pending_projection_work() == ()  # No GET adoption.
    previous = -1
    for _ in range(600):
        repair = queue.store().repair_projection_work(queue.task)
        assert 0 < repair.after_sequence - previous <= 256
        previous = repair.after_sequence
        if not repair.needs_repair:
            break
        assert queue.store().read_projection_work_repairs() == (repair,)
    assert repair.after_sequence == 599 and not repair.needs_repair
    (work,) = store.read_pending_projection_work()
    assert work.requested_through == 599
    assert store.read_projection_work_problem(work.scope) is None


def test_gap_is_durable_not_get_repair(queue):
    store = active(queue)
    queue.append(2, body="{}")
    counts = queue.table_counts()
    assert store.read_pending_projection_work() == ()
    assert store.read_projection_work_repairs()[0].wanted_through == 2
    assert queue.table_counts() == counts
    with pytest.raises(CheckpointNotReady):
        store.repair_projection_work(queue.task)
    queue.append(0)
    queue.append(1, body="{}")
    with queue.connect() as connection:
        queue.execute(connection, "UPDATE agent_tasks SET next_event_sequence=3")
    assert not store.repair_projection_work(queue.task).needs_repair
    (work,) = store.read_pending_projection_work()
    assert work.requested_through == 2


def test_dependency_wait_retains_failures_stale_cas_and_real_exhaustion(queue, monkeypatch):
    store = active(queue)
    queue.append(0)
    transient_failures(store, monkeypatch, 7)
    (work,) = store.read_pending_projection_work()
    assert store.defer_projection_work(work, problem_code="not_ready")
    problem = queue.store().read_projection_work_problem(work.scope)
    assert problem.attempts == 7 and problem.retry_at is None
    queue.append(2, body="{}")  # Gap is not a genuine wake.
    with queue.connect() as connection:
        queue.execute(connection, "UPDATE session_events SET task_sequence=0 WHERE sequence=0")
    assert queue.store().read_projection_work_problem(work.scope) == problem
    queue.append(1, body="{}")
    assert queue.store().read_projection_work_problem(work.scope) is None
    assert failure_count(store, work.scope) == 7
    assert not store.complete_projection_work(work, expected_through=work.requested_through)
    assert not store.defer_projection_work(work, problem_code="integrity")
    assert not store.repair_projection_work(queue.task).needs_repair
    (ready,) = queue.store().read_pending_projection_work()
    assert ready.requested_through == 2
    assert store.defer_projection_work(
        ready, problem_code="projection_failed", retry_after_seconds=1
    )
    capped = store.read_projection_work_problem(work.scope)
    assert capped.attempts == 8 and capped.retry_at is None
    queue.append(3, kind="message", run="new")  # Closure must not wake an exhausted fault.
    assert queue.store().read_projection_work_problem(work.scope) == capped
    assert store.retry_due_projection_work() == 0
    assert all(w.scope != work.scope for w in store.read_pending_projection_work())


def test_zero_failure_dependency_wait_explicit_retry_and_validation(queue):
    store = active(queue)
    queue.append(0)
    (work,) = store.read_pending_projection_work()
    assert store.defer_projection_work(work, problem_code="not_ready")
    assert store.read_projection_work_problem(work.scope).attempts == 0
    assert not store.retry_projection_work(work.scope, expected_attempt=1)
    assert store.retry_projection_work(work.scope, expected_attempt=0)
    (work,) = store.read_pending_projection_work()
    assert store.defer_projection_work(work, problem_code="not_ready")
    assert store.retry_due_projection_work() == 0
    for invalid in (True, -1, 2_147_483_648):
        with pytest.raises(ValueError):
            store.retry_projection_work(work.scope, expected_attempt=invalid)
    queue.append(1, body="{}")
    assert store.read_projection_work_problem(work.scope) is None
    assert failure_count(store, work.scope) == 0


def test_native_and_repair_headers_quote_percent_dollar_and_sql_text(queue):
    run = "run $$ '%s %(version)s ; DROP TABLE task_projection_work; --"
    queue.append(0, run=run)
    store = active(queue)
    assert not store.repair_projection_work(queue.task).needs_repair
    (work,) = store.read_pending_projection_work()
    assert work.run_id == run
    queue.append(1, kind="message", run=run + "next")
    rows = queue.work_rows()
    assert len(rows) == 2 and rows[0]["closed_through"] == 0


def test_sqlite_explicit_scalar_upgrade_preserves_legacy_problems_and_cursor(tmp_path):
    from agent_storage.projection_work_schema import SCHEMA

    fixture = QueueFixture("sqlite", tmp_path)
    anchor = fixture.append(0)
    legacy = SCHEMA.replace(
        " dependency_wait INTEGER NOT NULL DEFAULT 0 CHECK(dependency_wait IN (0,1)),\n", ""
    ).replace(
        ",\n CHECK(dependency_wait=0 OR (problem_code IS NOT NULL\n"
        " AND problem_code='not_ready' AND retry_at IS NULL))",
        "",
    )
    with fixture.connect() as connection:
        connection.executescript(legacy)
        connection.execute(
            "INSERT INTO task_projection_work_projectors VALUES ('local','ag-ui-v1',1,?,1)",
            (str(fixture.task),),
        )
        connection.execute(
            "INSERT INTO task_projection_work_routes VALUES ('local',?,'ag-ui-v1',0,0,?,0)",
            (str(fixture.task), anchor),
        )
        connection.execute(
            "INSERT INTO task_projection_work "
            "(deployment_namespace,task_id,anchor_key,projector_version,run_id,anchor_sequence,"
            "requested_through,revision,problem_code,problem_attempts) "
            "VALUES ('local',?,?,'ag-ui-v1','latest',0,0,6,'not_ready',7)",
            (str(fixture.task), anchor),
        )
        connection.execute("""CREATE TRIGGER session_events_work_insert
         AFTER INSERT ON session_events BEGIN SELECT RAISE(ABORT,'stale routing'); END""")
    fixture.install()  # Explicit initialization only: no GET adopts/rewrites legacy problems.
    store = fixture.store()
    assert store.bootstrap_projection_work()
    row = fixture.work_rows()[0]
    assert row["dependency_wait"] == 0 and row["problem_attempts"] == 7 and row["revision"] == 6
    fixture.append(1, body="{}")
    from agent_core.ports.task_projection_checkpoints import ProjectionScope

    scope = ProjectionScope(fixture.namespace, fixture.task, EventId(UUID(anchor)), "ag-ui-v1")
    assert store.read_projection_work_problem(scope).attempts == 7
    assert store.retry_projection_work(scope, expected_attempt=7)
    (work,) = store.read_pending_projection_work()
    assert store.defer_projection_work(work, problem_code="not_ready")
    fixture.append(2, body="{}")
    assert store.read_projection_work_problem(scope) is None
    assert failure_count(store, scope) == 7


def test_existing_checkpoint_ahead_of_partial_bootstrap_waits_for_exact_target(queue):
    queue.append(0)
    queue.append(1, body='{"evidence":"retained"}')
    store = active(queue)
    assert store.repair_projection_work(queue.task, limit=1).needs_repair
    (prefix,) = store.read_pending_projection_work()
    assert prefix.requested_through == 0
    # A checkpoint may predate enabling the queue; bounded repair discovers its prefix first.
    queue.set_head(prefix, through=1)
    (observed,) = store.read_pending_projection_work()
    assert observed.after_sequence == 1 and observed.requested_through == 0
    assert not store.complete_projection_work(observed, expected_through=0)
    assert store.read_projection_work_problem(observed.scope) is None
    assert not store.repair_projection_work(queue.task).needs_repair
    (caught_up,) = store.read_pending_projection_work()
    assert caught_up.after_sequence == caught_up.requested_through == 1
    assert not store.complete_projection_work(observed, expected_through=0)
    assert store.complete_projection_work(caught_up, expected_through=1)
    assert store.read_pending_projection_work() == ()
