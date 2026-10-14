"""Actual two-consumer Worker routing in SQLite and isolated native PostgreSQL."""

import os
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_integrations.ag_ui.checkpoint_consumer import AgUiCheckpointConsumer
from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
from agent_integrations.ag_ui.contracts import AgUiRunIdentity
from agent_storage import (
    PostgresAgentTaskStore,
    PostgresEventStore,
    PostgresProjectionStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
    postgres_control_plane_stores,
    sqlite_control_plane_stores,
)
from agent_storage.postgres.projection_work_migration import TASK_PROJECTION_WORK_MIGRATION
from agent_storage.postgres.projection_work_routing_migration import (
    TASK_PROJECTION_WORK_ROUTING_MIGRATION,
)
from agent_storage.projection_work_routing import COVERAGE, ORDINARY
from psycopg import sql
from psycopg.conninfo import make_conninfo
from zebra_agent_worker.ag_ui_projection_work import AgUiProjectionWorkService

from tests.agent_integrations.ag_ui_checkpoint_consumer_scratch import (
    _append,
    _command,
    _restore,
    _task,
)
from tests.agent_integrations.test_ag_ui_coverage_checkpoint_native import (
    prepare_session_projection,
)
from tests.agent_integrations.test_ag_ui_projection import _event
from tests.agent_storage.test_postgres_control_plane_composition import _ObjectReader


@pytest.fixture
def routing_dsn():
    configured = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not configured:
        pytest.skip("set the authorized scratch DSN for native routing")
    schema = "checkpoint_routing_" + uuid4().hex
    with psycopg.connect(configured) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        dsn = make_conninfo(configured, options=f"-c search_path={schema}")
        apply_postgres_migrations(dsn)
        with psycopg.connect(dsn) as connection:
            migration = TASK_PROJECTION_WORK_ROUTING_MIGRATION
            applied = connection.execute(
                "SELECT name,checksum FROM zebra_schema_migrations WHERE version=98"
            ).fetchone()
            assert applied == (migration.name, migration.checksum)
        yield dsn
    finally:
        with psycopg.connect(configured) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture(params=("sqlite", "postgres"))
def native(request, tmp_path):
    if request.param == "sqlite":
        return sqlite_control_plane_stores(tmp_path / "routing.sqlite")
    dsn = request.getfixturevalue("routing_dsn")
    bootstrap_control_plane_epoch(dsn, deployment_namespace="local")
    scope = OpaqueAuthorityScope(authority_issuer="test", namespace_id="test")
    return postgres_control_plane_stores(
        dsn,
        deployment_namespace="local",
        memory_cursor_signing_key=b"k" * 32,
        artifact_objects=_ObjectReader(),
        history_scope=scope,
        continuation_scope=scope,
    )


def queues(stores):
    ordinary, coverage = stores.projection_work, stores.coverage_projection_work
    assert ordinary is not None and coverage is not None
    return ordinary, coverage


def consumers(stores):
    return tuple(
        AgUiCheckpointConsumer(stores.tasks, queue, namespace="local") for queue in queues(stores)
    )


def query(stores, statement, params=()):
    with stores.tasks._database.connect() as connection:
        cursor = connection.execute(
            statement.replace("?", "%s") if hasattr(stores.tasks._database, "_dsn") else statement,
            params,
        )
        return cursor.fetchall() if cursor.description else []


def prepared(stores, task, sequence, marker="absent"):
    sequence += int(hasattr(stores.tasks._database, "_dsn"))
    source = _event(
        task.active_segment_id,
        sequence,
        EventType.TASK_PREPARED,
        {"title": "routing", "user_input": "PRIVATE_INPUT"},
    )
    if marker != "absent":
        # Historical raw presence, including JSON null, is stricter than today's validator.
        source = source.model_copy(
            update={"payload": source.payload | {"coverage_admission": marker}}
        )
    stores.events.append(source)


def drain(consumer):
    for _ in range(12):
        consumer.poll_once(budget_seconds=2)
        if (
            not consumer.work.read_pending_projection_work()
            and not consumer.work.read_projection_work_repairs()
        ):
            return
    pytest.fail("bounded routing failed to drain")


def test_historical_migration_generator_stays_frozen():
    assert TASK_PROJECTION_WORK_MIGRATION.checksum == (
        "a08e29f23387b57b0ed740702c65bedee740384226363e3d919f7689dc36201f"
    )
    assert TASK_PROJECTION_WORK_ROUTING_MIGRATION.version == 98
    assert TASK_PROJECTION_WORK_ROUTING_MIGRATION.checksum == (
        "a5c191da7be764473aa8083fe0af521e9cf412a03b48ebb89eb5a7b478fa8f46"
    )


@pytest.mark.parametrize("enabled_before_source", [False, True])
def test_real_normal_bootstrap_omits_admission_and_never_broadcasts(
    native,
    tmp_path,
    enabled_before_source,
):
    ordinary, coverage = queues(native)
    if enabled_before_source:
        ordinary.enable_projection_work()
        coverage.enable_projection_work()
    boot = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="normal",
            user_input="Inspect repository",
            workspace_root=tmp_path,
        )
    )
    assert "coverage_admission" not in boot.events[2].payload
    for source in boot.events:
        native.events.append(source)
    native.sessions.save_session(boot.session)
    task = native.tasks.ensure_for_session(boot.session.session_id)
    offset = int(hasattr(native.tasks._database, "_dsn"))
    _command(native.events, task, 3 - offset)
    for queue in (ordinary, coverage):
        if not enabled_before_source:
            queue.enable_projection_work()
            while not queue.bootstrap_projection_work(limit=1):
                pass
        assert not queue.repair_projection_work(task.task_id).needs_repair
    assert not native.tasks.read_run_header(task.task_id, "run").strict_coverage
    assert len(ordinary.read_pending_projection_work()) == 1
    assert not coverage.read_pending_projection_work()
    rows = query(
        native,
        "SELECT projector_version FROM task_projection_work_routes WHERE task_id=?",
        (str(task.task_id),),
    )
    assert [row["projector_version"] for row in rows] == [ORDINARY]


@pytest.mark.parametrize("enabled_before_source", [False, True])
def test_native_colliding_task_uuid_cannot_classify_or_fanout_across_tenants(
    native,
    enabled_before_source,
):
    if not hasattr(native.tasks._database, "_dsn"):
        pytest.skip("SQLite Task UUID is global; tenant collision is PostgreSQL-only")
    dsn = native.tasks._database._dsn
    other_namespace = "other-" + uuid4().hex
    bootstrap_control_plane_epoch(dsn, deployment_namespace=other_namespace)
    other_tasks = PostgresAgentTaskStore(dsn, deployment_namespace=other_namespace)
    other_events = PostgresEventStore(dsn, deployment_namespace=other_namespace)
    other_sessions = PostgresProjectionStore(dsn, deployment_namespace=other_namespace)
    session = Session.create(title="other strict Task").model_copy(
        update={"session_id": SessionId(uuid4())}
    )
    other_events.append(
        _event(session.session_id, 0, EventType.SESSION_CREATED, {"title": session.title})
    )
    other_sessions.save_session(session)
    other_tasks.ensure_for_session(session.session_id)
    other_events.append(
        _event(
            session.session_id,
            1,
            EventType.TASK_PREPARED,
            {"title": "strict", "user_input": "PRIVATE_OTHER"},
        ).model_copy(
            update={
                "payload": {
                    "title": "strict",
                    "user_input": "PRIVATE_OTHER",
                    "coverage_admission": None,
                }
            }
        )
    )
    ordinary, coverage = queues(native)
    if enabled_before_source:
        ordinary.enable_projection_work()
        coverage.enable_projection_work()
    task = _task(native.tasks, ordinal=session.session_id.int)
    _command(native.events, task)
    prepared(native, task, 1)
    if not enabled_before_source:
        for queue in (ordinary, coverage):
            queue.enable_projection_work()
            assert queue.bootstrap_projection_work()
    for queue in (ordinary, coverage):
        assert not queue.repair_projection_work(task.task_id).needs_repair
    assert not native.tasks.read_run_header(task.task_id, "run").strict_coverage
    assert len(ordinary.read_pending_projection_work()) == 1
    assert not coverage.read_pending_projection_work()
    rows = query(
        native,
        "SELECT projector_version FROM task_projection_work_routes "
        "WHERE deployment_namespace='local' AND task_id=?",
        (str(task.task_id),),
    )
    assert [row["projector_version"] for row in rows] == [ORDINARY]


@pytest.mark.parametrize("marker", ["absent", None, {}, "malformed"])
@pytest.mark.parametrize("enabled_before_source", [False, True])
def test_bootstrap_and_native_autorouting_select_only_source_owned_queue(
    native,
    marker,
    enabled_before_source,
):
    ordinary, coverage = queues(native)
    if enabled_before_source:
        ordinary.enable_projection_work()
        coverage.enable_projection_work()
    task = _task(native.tasks, ordinal=uuid4().int)
    _command(native.events, task)
    prepared(native, task, 1, marker)
    expected = ORDINARY if marker == "absent" else COVERAGE
    if not enabled_before_source:
        ordinary.enable_projection_work()
        coverage.enable_projection_work()
        for queue in (ordinary, coverage):
            while not queue.bootstrap_projection_work(limit=1):
                pass
        rows = query(
            native,
            "SELECT projector_version FROM task_projection_work_routes WHERE task_id=?",
            (str(task.task_id),),
        )
        assert {row["projector_version"] for row in rows} == {expected}
    for queue in (ordinary, coverage):
        while queue.repair_projection_work(task.task_id, limit=2).needs_repair:
            pass
    if expected == COVERAGE:
        # The pre-admission command was legitimately ordinary. A late marker
        # parks that old queue rather than ACKing or deleting its closed work.
        wrong_consumer, _ = consumers(native)
        for work in ordinary.read_pending_projection_work():
            assert not wrong_consumer.materialize_once(work)
    rows = query(
        native,
        "SELECT projector_version FROM task_projection_work WHERE task_id=? "
        "AND problem_code IS NULL",
        (str(task.task_id),),
    )
    assert [row["projector_version"] for row in rows] == [expected]
    wrong = coverage if expected == ORDINARY else ordinary
    assert not wrong.read_pending_projection_work()
    assert not wrong.read_projection_work_repairs()


def test_wrong_queue_parks_without_body_reads_timer_retry_or_failure_charge(native, monkeypatch):
    ordinary, coverage = queues(native)
    ordinary.enable_projection_work()
    coverage.enable_projection_work()
    task = _task(native.tasks, ordinal=uuid4().int)
    _command(native.events, task)
    prepared(native, task, 1)
    ordinary.repair_projection_work(task.task_id)
    query(
        native,
        "INSERT INTO task_projection_work "
        "(deployment_namespace,task_id,anchor_key,projector_version,run_id,"
        "anchor_sequence,requested_through) "
        "SELECT deployment_namespace,task_id,anchor_key,?,run_id,anchor_sequence,requested_through "
        "FROM task_projection_work WHERE task_id=? AND projector_version=?",
        (COVERAGE, str(task.task_id), ORDINARY),
    )
    (work,) = coverage.read_pending_projection_work()
    _, consumer = consumers(native)

    def forbidden(*args, **kwargs):
        raise AssertionError("wrong queue touched checkpoint bodies or summaries")

    monkeypatch.setattr(native.tasks, "read_event_page", forbidden)
    consumer.read_summaries = type("NoSummary", (), {"backfill_read_summary": forbidden})()
    assert consumer.materialize_once(work) is False
    problem = coverage.read_projection_work_problem(work.scope)
    assert problem.code == "not_ready" and problem.attempts == 0
    assert problem.retry_at is None
    assert not coverage.read_pending_projection_work()
    for _ in range(5):
        assert coverage.retry_due_projection_work() == 0
        assert consumer.poll_once(budget_seconds=2) == 0
    assert not coverage.complete_projection_work(work, expected_through=work.requested_through)


def test_unavailable_current_privacy_header_cannot_publish_or_ack(native, monkeypatch):
    ordinary, _ = queues(native)
    ordinary.enable_projection_work()
    task = _task(native.tasks, ordinal=uuid4().int)
    _command(native.events, task)
    prepared(native, task, 1)
    ordinary.repair_projection_work(task.task_id)
    (work,) = ordinary.read_pending_projection_work()
    read = native.tasks.read_run_header

    def unavailable(task_id, run_id, **kwargs):
        if "through_sequence" not in kwargs:
            raise CheckpointNotReady("current Task privacy unavailable")
        return read(task_id, run_id, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("privacy failure reached checkpoint publication")

    monkeypatch.setattr(native.tasks, "read_run_header", unavailable)
    monkeypatch.setattr(native.tasks, "read_event_page", forbidden)
    monkeypatch.setattr(ordinary, "complete_projection_work", forbidden)
    consumer, _ = consumers(native)
    with pytest.raises(CheckpointNotReady, match="privacy unavailable"):
        consumer.materialize_once(work)
    assert native.tasks.read_checkpoint_head(work.scope).through_sequence == -1
    assert ordinary.read_pending_projection_work() == (work,)
    assert ordinary.read_projection_work_problem(work.scope) is None


@pytest.mark.parametrize("marker", [None, {}, "malformed"])
def test_actual_worker_late_flip_requeues_closed_anchors_bounded_and_cold_privacy(
    native,
    monkeypatch,
    marker,
):
    ordinary, coverage = queues(native)
    for queue in (ordinary, coverage):
        queue.enable_projection_work()
    task = _task(native.tasks, ordinal=uuid4().int)
    _command(native.events, task)
    prepared(native, task, 1)
    _append(
        native.events,
        task,
        2,
        EventType.MODEL_RESPONSE_RECEIVED,
        {"assistant_message": "PRIVATE_PREFIX"},
    )
    _command(native.events, task, 3, "next")
    prepared(native, task, 4)
    _append(
        native.events,
        task,
        5,
        EventType.MODEL_RESPONSE_RECEIVED,
        {"assistant_message": "PRIVATE_SECOND"},
    )
    _command(native.events, task, 6, "last")
    if hasattr(native.tasks._database, "_dsn"):
        prepare_session_projection(native, task.active_segment_id)
    consumer, strict_consumer = consumers(native)
    drain(consumer)
    assert not coverage.read_pending_projection_work()
    identity = AgUiRunIdentity(
        session_id=task.active_segment_id, thread_id=str(task.task_id), run_id="run"
    )
    observer = AgUiCheckpointObserver(native.tasks, namespace="local")
    snapshot = observer.snapshot(task.task_id, identity)
    frames = observer.iter_page_frames(snapshot, observer.read_page(snapshot, 0), identity)
    next(frames)
    # Model the old broadcast queue: one dependency-parked closed Run and one
    # already ACKed closed Run. An upgrade must revive both, not merely new Runs.
    query(
        native,
        "INSERT INTO task_projection_work "
        "(deployment_namespace,task_id,anchor_key,projector_version,run_id,anchor_sequence,"
        "requested_through,closed_through,pending,problem_code,dependency_wait,problem_attempts) "
        "SELECT deployment_namespace,task_id,anchor_key,?,run_id,anchor_sequence,"
        "requested_through,closed_through,CASE WHEN run_id='run' THEN 1 ELSE 0 END,"
        "CASE WHEN run_id='run' THEN 'not_ready' END,CASE WHEN run_id='run' THEN 1 ELSE 0 END,7 "
        "FROM task_projection_work WHERE task_id=? AND projector_version=? "
        "AND closed_through IS NOT NULL",
        (COVERAGE, str(task.task_id), ORDINARY),
    )
    offset = int(hasattr(native.tasks._database, "_dsn"))
    query(
        native,
        "INSERT INTO task_projection_work_routes "
        "(deployment_namespace,task_id,projector_version,observed_through,wanted_through) "
        "VALUES ('local',?,?,?,?)",
        (str(task.task_id), COVERAGE, 6 + offset, 6 + offset),
    )
    prepared(native, task, 7, marker)
    (routed,) = query(
        native,
        "SELECT observed_through,wanted_through,privacy_frontier "
        "FROM task_projection_work_routes WHERE task_id=? AND projector_version=?",
        (str(task.task_id), COVERAGE),
    )
    assert (routed["observed_through"], routed["wanted_through"], routed["privacy_frontier"]) == (
        -1,
        7 + offset,
        7 + offset,
    )  # Same append transaction; no later source event or bootstrap wake needed.
    if hasattr(native.tasks._database, "_dsn"):
        prepare_session_projection(native, task.active_segment_id)
    with pytest.raises(CheckpointNotReady, match="privacy changed"):
        next(frames)
    assert observer.snapshot(task.task_id, identity).head.through_sequence == -1
    repaired = coverage.repair_projection_work(task.task_id, limit=2)
    assert repaired.after_sequence <= 1 and repaired.needs_repair
    assert coverage.read_pending_projection_work()
    assert ordinary.repair_projection_work(task.task_id, limit=2).needs_repair is False
    # A work target is not an ACK: the strict checkpoint must really reach it.
    first = coverage.read_pending_projection_work()[0]
    assert not coverage.complete_projection_work(first, expected_through=first.requested_through)
    for _ in range(12):
        if not coverage.repair_projection_work(task.task_id, limit=2).needs_repair:
            break
    else:
        pytest.fail("privacy replay did not advance its bounded scalar cursor")
    rows = query(
        native,
        "SELECT run_id,requested_through,closed_through,problem_attempts,pending "
        "FROM task_projection_work WHERE task_id=? AND projector_version=? "
        "ORDER BY anchor_sequence",
        (str(task.task_id), COVERAGE),
    )
    assert [(r["run_id"], r["closed_through"]) for r in rows[:2]] == [
        ("run", 2 + offset),
        ("next", 5 + offset),
    ]
    assert all(r["pending"] == 1 and r["problem_attempts"] == 7 for r in rows[:2])
    completed = Event()
    seen = set()
    original = coverage.complete_projection_work

    def ack(work, *, expected_through):
        accepted = original(work, expected_through=expected_through)
        if accepted:
            seen.add(work.run_id)
            if {"run", "next", "last"} <= seen:
                completed.set()
        return accepted

    monkeypatch.setattr(coverage, "complete_projection_work", ack)
    service = AgUiProjectionWorkService(
        consumer, coverage_consumer=strict_consumer, interval_seconds=0.01
    )
    try:
        service.start()
        assert completed.wait(8), (
            "actual Worker consumers did not publish the strict closed windows"
        )
    finally:
        service.close()
    assert service._thread is not None and not service._thread.is_alive()
    assert not coverage.read_pending_projection_work()
    cold = AgUiCheckpointObserver(_restore(native.tasks), namespace="local")
    strict_snapshot = cold.snapshot(task.task_id, identity)
    actual = list(
        cold.iter_page_frames(strict_snapshot, cold.read_page(strict_snapshot, 0), identity)
    )
    assert "PRIVATE" not in str(actual)
    assert strict_snapshot.head.scope.projector_version == COVERAGE
    assert all(
        r["problem_attempts"] == 7
        for r in query(
            native,
            "SELECT problem_attempts FROM task_projection_work WHERE task_id=? "
            "AND projector_version=? AND closed_through IS NOT NULL",
            (str(task.task_id), COVERAGE),
        )
    )
