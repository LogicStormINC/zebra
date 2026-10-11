"""Coverage cells upgrade old native stores and survive actual cold replay."""

import os
import sqlite3
from uuid import uuid4

import psycopg
import pytest
from ag_ui.encoder import EventEncoder
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady, ProjectionScope
from agent_integrations.ag_ui.checkpoint_binding import build_projection_page_plan
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
from agent_integrations.ag_ui.checkpoint_plan import checkpoint_version
from agent_integrations.ag_ui.contracts import AgUiCursor, AgUiRunIdentity
from agent_integrations.ag_ui.coverage_checkpoint import coverage_chunk_count, coverage_keys
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_storage.postgres import apply_postgres_migrations
from agent_storage.postgres.task_projection_coverage_cells_migration import (
    TASK_PROJECTION_COVERAGE_CELLS_MIGRATION,
)
from agent_storage.postgres.task_replay_coverage_privacy_migration import (
    TASK_REPLAY_COVERAGE_PRIVACY_MIGRATION,
)
from agent_storage.task_projection_checkpoint_schema import SCHEMA
from agent_storage.task_projection_coverage_cells_schema import (
    initialize_task_projection_checkpoints,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests.agent_core.test_coverage_persistence import binding
from tests.agent_integrations import test_ag_ui_binding_persistence as persistence
from tests.agent_integrations.binding_store_cases import (
    NOW,
    append,
    command,
    publish,
    ready,
    resolve,
    root,
)

native_stores = persistence.stores


@pytest.mark.parametrize("marker", [None, {}, "malformed"])
def test_native_late_admission_flips_privacy_before_next_frame(upgraded_stores, marker):
    stores = upgraded_stores
    segment = root(stores)
    task = TaskId(segment)
    append(
        stores,
        segment,
        2,
        EventType.MODEL_RESPONSE_RECEIVED,
        {"assistant_message": "PRIVATE_PREFIX"},
    )
    run = ready(stores.tasks, task)
    assert not run.strict_coverage
    scope = ProjectionScope(stores.namespace, task, run.anchor.event_id, checkpoint_version(run))
    resolve(stores.tasks, run, scope)
    publish(stores.tasks, run, scope)
    identity = AgUiRunIdentity(session_id=segment, thread_id=str(task), run_id="run")
    observer = AgUiCheckpointObserver(stores.cold(), namespace=stores.namespace)
    snapshot = observer.snapshot(task, identity)
    page = observer.read_page(snapshot, 1)
    frames = observer.iter_page_frames(snapshot, page, identity)
    assert "PRIVATE_PREFIX" not in str(next(frames))  # Start frame, before content.
    command(stores, segment, 3, "next")
    # Preserve historical presence verbatim; today's admission validator strips
    # null and rejects malformed markers, but stored source privacy must not.
    source = SessionEvent.create(
        session_id=segment,
        sequence=4,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={"title": "strict", "user_input": "private"},
        created_at=NOW,
    ).model_copy(
        update={
            "payload": {
                "title": "strict",
                "user_input": "private",
                "coverage_admission": marker,
            }
        }
    )
    stores.events.append(source)
    strict = ready(stores.tasks, task)
    assert strict.strict_coverage
    assert not stores.tasks.read_run_header(task, "run", through_sequence=2).strict_coverage
    assert stores.tasks.read_run_header(task, "unknown").strict_coverage
    with pytest.raises(CheckpointNotReady, match="privacy changed"):
        next(frames)
    strict_scope = observer.snapshot(task, identity).head.scope
    assert strict_scope != scope
    assert stores.tasks.read_checkpoint_head(strict_scope).through_sequence == -1
    resolve(stores.tasks, strict, strict_scope)
    publish(stores.tasks, strict, strict_scope)
    snapshot = observer.snapshot(task, identity)
    actual = list(observer.iter_page_frames(snapshot, observer.read_page(snapshot, 0), identity))
    oracle = stores.tasks.read_events(task, -1)
    assert actual == list(AgUiTaskProjector().project_task_events(oracle, identity))
    assert "PRIVATE" not in str(actual)
    assert stores.tasks.read_run_header(task, "run").strict_coverage
    assert stores.tasks.read_run_header(task, "next").strict_coverage
    with stores.tasks._database.connect() as connection:
        if hasattr(stores.tasks._database, "_dsn"):
            plan = connection.execute(
                "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT 1 FROM task_replay_coverage_privacy "
                "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence<=%s "
                "LIMIT 1",
                (stores.namespace, task, 4),
            ).fetchone()
            assert "session_events_coverage_privacy" in str(plan), plan

            def nodes(node):
                yield node
                for child in node.get("Plans", []):
                    yield from nodes(child)

            for node in nodes(plan["QUERY PLAN"][0]["Plan"]):
                if node.get("Relation Name") == "session_events":
                    assert node["Node Type"] == "Index Only Scan", node
                    assert node["Index Name"] == "session_events_coverage_privacy", node
                    assert node.get("Rows Removed by Filter", 0) == 0, node
                    assert node["Actual Rows"] * node["Actual Loops"] <= 2, node
                    assert "payload" not in str(node).lower(), node
        else:
            plan = connection.execute(
                "EXPLAIN QUERY PLAN SELECT 1 FROM task_replay_coverage_privacy "
                "INDEXED BY session_events_coverage_privacy "
                "WHERE task_id=? AND task_sequence<=? LIMIT 1",
                (str(task), 4),
            ).fetchall()
            assert "session_events_coverage_privacy" in str([tuple(row) for row in plan])


@pytest.fixture(scope="module")
def metadata_dsn():
    configured = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not configured:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN for isolated native checkpoints")
    # Reuse schema isolation: the owned scratch role needs no CREATEDB privilege.
    schema = f"coverage_checkpoint_{uuid4().hex}"
    with psycopg.connect(configured) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        dsn = make_conninfo(configured, options=f"-c search_path={schema}")
        apply_postgres_migrations(dsn)
        yield dsn
    finally:
        with psycopg.connect(configured) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def upgraded_stores(native_stores):
    stores = native_stores
    if hasattr(stores.tasks._database, "_dsn"):
        with stores.tasks._database.connect() as connection:
            historic = connection.execute(
                "SELECT version,name,checksum FROM zebra_schema_migrations "
                "WHERE version NOT IN (95,97) "
                "ORDER BY version"
            ).fetchall()
            for migration in (
                TASK_PROJECTION_COVERAGE_CELLS_MIGRATION,
                TASK_REPLAY_COVERAGE_PRIVACY_MIGRATION,
            ):
                applied = connection.execute(
                    "SELECT name,checksum FROM zebra_schema_migrations WHERE version=%s",
                    (migration.version,),
                ).fetchone()
                if applied is None:  # Main registers the catalog; this database is isolated.
                    for statement in migration.statements:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO zebra_schema_migrations(version,name,checksum) "
                        "VALUES (%s,%s,%s)",
                        (migration.version, migration.name, migration.checksum),
                    )
                else:
                    assert applied == {"name": migration.name, "checksum": migration.checksum}
            assert (
                historic
                == connection.execute(
                    "SELECT version,name,checksum FROM zebra_schema_migrations "
                    "WHERE version NOT IN (95,97) "
                    "ORDER BY version"
                ).fetchall()
            )
    return stores


@pytest.mark.parametrize("page_size", [1, 256])
def test_native_commit_read_and_cold_resume_retain_private_progress_authority(
    upgraded_stores,
    monkeypatch,
    page_size,
):
    stores = upgraded_stores
    segment = root(stores)
    task = TaskId(segment)
    intent = binding().model_copy(update={"session_id": segment, "task_id": task})
    snapshot = intent.snapshot.model_copy(
        update={
            "manifest_artifact_ref": "artifact://" + "雪" * 1500,
        }
    )
    intent = intent.model_copy(update={"snapshot": snapshot})
    common = {"run_id": intent.run_id, "namespace": intent.namespace}
    for position, kind, payload in (
        (2, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "PRIVATE_PREFIX"}),
        (
            3,
            EventType.TASK_PREPARED,
            {"title": "coverage", "user_input": "private request", "coverage_admission": None},
        ),
        (
            4,
            EventType.COVERAGE_MANIFEST_COMMITTED,
            common | {"binding": intent.model_dump(mode="json"), "expected_count": 4},
        ),
        (5, EventType.COVERAGE_BATCH_ACCEPTED, common | {"result_count": 2}),
        (6, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "PRIVATE_TAIL"}),
        (7, EventType.COVERAGE_BATCH_ACCEPTED, common | {"result_count": 2}),
        (8, EventType.COVERAGE_RUN_CANCELLED, common),
    ):
        append(stores, segment, position, kind, payload)
    run = ready(stores.tasks, task)
    assert run.strict_coverage
    scope = ProjectionScope(stores.namespace, task, run.anchor.event_id, checkpoint_version(run))
    identity = AgUiRunIdentity(session_id=segment, thread_id=str(task), run_id=run.run_id)
    oracle = stores.tasks.read_events(task, -1)  # Oracle only, before forbidding history reads.
    resolve(stores.tasks, run, scope)
    materializer = AgUiCheckpointMaterializer(stores.tasks)
    after = -1
    while after < run.highwater:
        page = stores.tasks.read_event_page(
            task,
            after,
            limit=page_size,
            through_sequence=run.highwater,
        )
        transition = materializer.prepare_page(
            page,
            build_projection_page_plan(stores.tasks, page, run, scope, identity),
            scope,
            identity,
        )
        stores.tasks.commit_projection_page(transition)
        after = page.next_sequence
    cold = stores.cold()

    def forbidden(*args, **kwargs):
        raise AssertionError("cold checkpoint replay requested full history")

    monkeypatch.setattr(cold, "read_events", forbidden)
    monkeypatch.setattr(stores.events, "list_for_session", forbidden)
    observer = AgUiCheckpointObserver(cold, namespace=stores.namespace)
    snapshot = observer.snapshot(task, identity)
    assert snapshot.run == run and snapshot.head.scope == scope
    target = oracle[5]
    metadata = cold.read_cells_at(scope, target.task_sequence, coverage_keys(target.event))
    assert coverage_chunk_count(target.event, metadata) > 2
    actual = []
    after = run.start - 1
    while after < run.highwater:
        page = cold.read_event_page(task, after, limit=1, through_sequence=run.highwater)
        for entry in page.events:
            actual.extend(
                AgUiCheckpointMaterializer(cold).iter_event_frames(
                    scope,
                    entry,
                    identity,
                    run=run,
                )
            )
        after = page.next_sequence
    observed = []
    after = run.start - 1
    while (page := observer.read_page(snapshot, after)) is not None:
        observed.extend(observer.iter_page_frames(snapshot, page, identity))
        after = page.next_sequence
    assert observed == actual
    assert actual == list(AgUiTaskProjector().project_task_events(oracle, identity))
    assert "PRIVATE" not in str(actual) and "artifact://" not in str(actual)
    encoder = EventEncoder()
    wire = [f"id: {cursor.encode()}\n{encoder.encode(frame)}" for cursor, frame in actual]
    assert "PRIVATE" not in "".join(wire) and "artifact://" not in "".join(wire)
    assert [AgUiCursor.decode(frame.splitlines()[0][4:]) for frame in wire] == [
        cursor for cursor, _ in actual
    ]
    progress = [
        frame.value
        for _, frame in actual
        if getattr(frame, "name", None) == "zebra.coverage_progress"
    ]
    assert [row["accepted_units"] for row in progress] == [0, 2, 4, 4]
    for cursor, _ in actual:
        entry = cold.read_event_page(
            task,
            cursor.sequence - 1,
            limit=1,
            through_sequence=run.highwater,
        ).events[0]
        resumed = list(
            AgUiCheckpointMaterializer(cold).iter_event_frames(
                scope,
                entry,
                identity,
                run=run,
                after=cursor,
            )
        )
        assert resumed == [
            (c, f)
            for c, f in actual
            if c.sequence == cursor.sequence and c.frame_index > cursor.frame_index
        ]


def test_sqlite_upgrade_preserves_existing_cells_indexes_and_is_idempotent():
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(SCHEMA)
        connection.execute("CREATE INDEX fixture_cell_lookup ON task_projection_cells(cell_key)")
        connection.execute("CREATE TABLE fixture_cell_audit(cell_kind TEXT)")
        connection.execute(
            "CREATE TRIGGER fixture_cell_insert AFTER INSERT ON task_projection_cells "
            "BEGIN INSERT INTO fixture_cell_audit VALUES (NEW.cell_kind); END"
        )
        old = ("local", "task", "", "ag-ui-v1", "segment", "text_message", "call", 0, "text", 10)
        connection.execute("INSERT INTO task_projection_cells VALUES (?,?,?,?,?,?,?,?,?,?)", old)
        connection.commit()
        initialize_task_projection_checkpoints(connection)
        initialize_task_projection_checkpoints(connection)
        assert connection.execute("SELECT * FROM task_projection_cells").fetchall() == [old]
        assert connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE name='fixture_cell_lookup'"
        ).fetchone() == (1,)
        assert connection.execute("SELECT * FROM fixture_cell_audit").fetchall() == [
            ("text_message",),
        ]
        row = (*old[:5], "coverage", *old[6:8], '{"accepted_units":2}', old[9])
        connection.execute("INSERT INTO task_projection_cells VALUES (?,?,?,?,?,?,?,?,?,?)", row)
        assert connection.execute("SELECT * FROM fixture_cell_audit").fetchall() == [
            ("text_message",),
            ("coverage",),
        ]
        for kind, value in (("unknown", "1"), ("tool_call", "not-membership")):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO task_projection_cells VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (*old[:5], kind, *old[6:8], value, old[9]),
                )


def test_pg_upgrade_retains_cell_kind_membership_byte_and_source_guards(upgraded_stores):
    stores = upgraded_stores
    if not hasattr(stores.tasks._database, "_dsn"):
        pytest.skip("PostgreSQL constraints only")
    segment = root(stores)
    run = ready(stores.tasks, TaskId(segment))
    scope = ProjectionScope(
        stores.namespace,
        run.task_id,
        run.anchor.event_id,
        checkpoint_version(run),
    )
    resolve(stores.tasks, run, scope)
    publish(stores.tasks, run, scope)
    with stores.tasks._database.connect() as connection:
        before = connection.execute("SELECT * FROM task_projection_cells").fetchall()
        for kind, value, byte_count in (
            ("unknown", "1", 280),
            ("tool_call", "bad", 292),
            ("coverage", "state", 1),
        ):
            with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                connection.execute(
                    "INSERT INTO task_projection_cells VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        scope.namespace,
                        scope.task_id,
                        str(scope.anchor_event_id),
                        scope.projector_version,
                        segment,
                        kind,
                        "key",
                        1,
                        value,
                        byte_count,
                    ),
                )
        with pytest.raises(psycopg.errors.ForeignKeyViolation), connection.transaction():
            connection.execute(
                "INSERT INTO task_projection_cells VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    scope.namespace,
                    scope.task_id,
                    str(scope.anchor_event_id),
                    scope.projector_version,
                    segment,
                    "coverage",
                    "key",
                    2,
                    "state",
                    304,
                ),
            )
        assert before == connection.execute("SELECT * FROM task_projection_cells").fetchall()


def test_sqlite_upgrade_failure_rolls_back_without_losing_old_cells():
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(SCHEMA)
        invalid = ("local", "task", "", "v1", "segment", "tool_call", "key", 0, "bad", 10)
        connection.execute(
            "INSERT INTO task_projection_cells VALUES (?,?,?,?,?,?,?,?,?,?)",
            invalid,
        )
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            initialize_task_projection_checkpoints(connection)
        assert connection.execute("SELECT * FROM task_projection_cells").fetchall() == [invalid]
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE name='task_projection_cells_coverage'"
            ).fetchone()
            is None
        )
