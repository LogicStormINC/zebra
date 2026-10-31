"""Real PG header reads: denied body access, fixed plans, atomic writes and deadlines."""

import time
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.session_observation_headers_migration import (
    SESSION_OBSERVATION_HEADERS_MIGRATION,
)
from agent_storage.postgres.task_io import TaskIoConnection, task_io_deadline
from agent_storage.session_observation_headers import prepare_session_observation_headers
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from tests.agent_storage.test_postgres_scalar_task_replay_headers import scratch as _scratch_fixture

scratch = _scratch_fixture
NS = "observation-header-probe"


def install(dsn: str, *, derived: bool = True) -> None:
    with psycopg.connect(dsn) as database:
        database.execute("ALTER TABLE agent_tasks ADD COLUMN active_segment_id UUID")
        database.execute("""CREATE TABLE session_projections (
            deployment_namespace TEXT NOT NULL,session_id UUID NOT NULL,title TEXT NOT NULL,
            status TEXT NOT NULL,current_sequence BIGINT NOT NULL,
            clarification_context_json JSONB,approval_context_json JSONB,task_plan_json JSONB,
            PRIMARY KEY(deployment_namespace,session_id))""")
        if derived:
            for statement in SESSION_OBSERVATION_HEADERS_MIGRATION.statements:
                database.execute(statement)


def insert(database, identity: UUID, *, namespace: str = NS, title: str = "Header") -> None:
    database.execute(
        "INSERT INTO session_projections VALUES (%s,%s,%s,'ready',7,NULL,NULL,NULL)",
        (namespace, identity, title),
    )
    database.execute(
        "INSERT INTO agent_tasks VALUES (%s,%s,11,'ready',%s)",
        (namespace, identity, identity),
    )


def test_native_trigger_atomicity_rollback_delete_and_namespace(scratch) -> None:
    dsn, _ = scratch
    install(dsn)
    identity = uuid4()
    store = PostgresAgentTaskStore(dsn, deployment_namespace=NS)
    with psycopg.connect(dsn) as database:
        insert(database, identity, title="图" * 800)
        insert(database, identity, namespace="foreign", title="Foreign")
    header = store.read_task_header(TaskId(identity))
    assert header is not None and header.title == "图" * 512 and header.title_truncated
    assert header.current_sequence == 10 and header.active_segment_sequence == 7
    with psycopg.connect(dsn) as database:
        database.execute(
            "UPDATE session_projections SET title='New',current_sequence=8 "
            "WHERE deployment_namespace=%s",
            (NS,),
        )
        database.rollback()
    assert store.read_task_header(TaskId(identity)) == header
    with psycopg.connect(dsn) as database:
        database.execute("DELETE FROM session_projections WHERE deployment_namespace=%s", (NS,))
    missing = store.read_task_header(TaskId(identity))
    assert missing is not None and missing.title is None and missing.status is None
    foreign = PostgresAgentTaskStore(dsn, deployment_namespace="foreign").read_task_header(
        TaskId(identity)
    )
    assert foreign is not None and foreign.title == "Foreign"
    assert (
        PostgresAgentTaskStore(dsn, deployment_namespace="unknown").read_task_header(
            TaskId(identity)
        )
        is None
    )


@pytest.mark.parametrize("size", [1_000, 10_000, 100_000])
def test_actual_header_query_has_indexed_fixed_size_plan_without_body_permissions(
    scratch, monkeypatch: pytest.MonkeyPatch, size: int
) -> None:
    dsn, role = scratch
    install(dsn)
    identity = uuid4()
    with psycopg.connect(dsn, row_factory=dict_row) as database:
        database.execute(
            "INSERT INTO session_projections SELECT %s,md5(n::text)::uuid,"
            "'Small','ready',0,NULL,NULL,NULL "
            "FROM generate_series(1,%s) n",
            (NS, size),
        )
        database.execute(
            "INSERT INTO agent_tasks SELECT deployment_namespace,session_id,1,'ready',session_id "
            "FROM session_projections"
        )
        insert(database, identity)
        database.execute(
            "UPDATE session_projections SET task_plan_json=%s,approval_context_json=%s "
            "WHERE deployment_namespace=%s AND session_id=%s",
            (Jsonb({"large": "x" * 8_000_000}), Jsonb({"large": "y" * 8_000_000}), NS, identity),
        )
        database.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
        schema = database.execute("SELECT current_schema() AS name").fetchone()["name"]
        database.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            )
        )
        database.execute(
            sql.SQL("GRANT SELECT ON agent_tasks,session_observation_headers TO {}").format(
                sql.Identifier(role)
            )
        )
        database.execute("ANALYZE agent_tasks")
        database.execute("ANALYZE session_observation_headers")
    settings = conninfo_to_dict(dsn)
    restricted = make_conninfo(dsn, options=settings["options"] + f" -c role={role}")
    captured = []
    original = TaskIoConnection.execute

    def record(database, query, parameters=None, **kwargs):
        if isinstance(query, str) and "FROM agent_tasks t LEFT JOIN" in query:
            captured.append((query, parameters))
        return original(database, query, parameters, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", record)
    header = PostgresAgentTaskStore(restricted, deployment_namespace=NS).read_task_header(
        TaskId(identity)
    )
    assert header is not None and header.title == "Header" and header.current_sequence == 10
    assert len(captured) == 1
    with psycopg.connect(restricted, row_factory=dict_row) as database:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), database.transaction():
            database.execute("SELECT task_plan_json FROM session_projections")
        query, parameters = captured[0]
        plan = database.execute(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + query, parameters
        ).fetchone()["QUERY PLAN"][0]["Plan"]

    def nodes(node):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)

    relations = [node for node in nodes(plan) if node.get("Relation Name")]
    assert {node["Relation Name"] for node in relations} == {
        "agent_tasks",
        "session_observation_headers",
    }
    assert all(node["Node Type"] in {"Index Scan", "Index Only Scan"} for node in relations)
    assert all(node["Actual Rows"] <= 1 for node in relations)
    assert plan["Actual Rows"] == 1


def test_legacy_header_preparation_is_explicit_paged_and_transactional(scratch) -> None:
    dsn, _ = scratch
    install(dsn, derived=False)
    with psycopg.connect(dsn) as database:
        database.execute(
            "INSERT INTO session_projections SELECT %s,md5(n::text)::uuid,"
            "'Legacy','ready',0,NULL,NULL,NULL "
            "FROM generate_series(1,600) n",
            (NS,),
        )
        database.execute(
            "INSERT INTO agent_tasks SELECT deployment_namespace,session_id,1,'ready',session_id "
            "FROM session_projections"
        )
        for statement in SESSION_OBSERVATION_HEADERS_MIGRATION.statements:
            database.execute(statement)
    with psycopg.connect(dsn, row_factory=dict_row) as database:
        task = database.execute("SELECT task_id FROM agent_tasks LIMIT 1").fetchone()["task_id"]
        missing = PostgresAgentTaskStore(dsn, deployment_namespace=NS).read_task_header(
            TaskId(task)
        )
        assert missing is not None and missing.title is None
        first = prepare_session_observation_headers(
            database, deployment_namespace=NS, postgres=True
        )
        assert len(first) == 256
        database.rollback()
        assert (
            database.execute("SELECT COUNT(*) AS n FROM session_observation_headers").fetchone()[
                "n"
            ]
            == 0
        )
        first = prepare_session_observation_headers(
            database, deployment_namespace=NS, postgres=True
        )
    with psycopg.connect(dsn, row_factory=dict_row) as database:
        second = prepare_session_observation_headers(
            database, deployment_namespace=NS, after_session_id=first[-1], postgres=True
        )
        third = prepare_session_observation_headers(
            database, deployment_namespace=NS, after_session_id=second[-1], postgres=True
        )
        assert (len(first), len(second), len(third)) == (256, 256, 88)
        assert len(set((*first, *second, *third))) == 600
        assert (
            prepare_session_observation_headers(
                database, deployment_namespace=NS, after_session_id=third[-1], postgres=True
            )
            == ()
        )


def test_header_missing_positions_never_adopts_and_actual_lock_deadline_cancels(scratch) -> None:
    dsn, _ = scratch
    install(dsn)
    identity = uuid4()
    label = f"header-deadline-{uuid4().hex}"
    bounded_dsn = make_conninfo(dsn, application_name=label)
    store = PostgresAgentTaskStore(bounded_dsn, deployment_namespace=NS)
    with psycopg.connect(dsn) as database:
        insert(database, identity)
        database.execute("UPDATE agent_tasks SET event_position_state='pending'")
    with pytest.raises(CheckpointNotReady):
        store.read_task_header(TaskId(identity))
    with psycopg.connect(dsn) as holder:
        holder.execute("UPDATE agent_tasks SET event_position_state='ready'")
        holder.commit()
        holder.execute("LOCK TABLE session_observation_headers IN ACCESS EXCLUSIVE MODE")
        started = time.monotonic()
        with pytest.raises((TimeoutError, psycopg.errors.LockNotAvailable)):
            with task_io_deadline(started + 0.25):
                store.read_task_header(TaskId(identity))
        assert time.monotonic() - started < 0.7
    with psycopg.connect(dsn, autocommit=True) as verify:
        until = time.monotonic() + 1
        while verify.execute(
            "SELECT 1 FROM pg_stat_activity WHERE application_name=%s", (label,)
        ).fetchone():
            assert time.monotonic() < until, "deadline left the native database query alive"
            time.sleep(0.01)
    assert store.read_task_header(TaskId(identity)) is not None


def test_native_preparation_deadline_rolls_back_and_does_not_change_global_gucs(scratch) -> None:
    dsn, _ = scratch
    install(dsn)
    with psycopg.connect(dsn) as database:
        database.execute(
            "INSERT INTO session_projections SELECT %s,md5(n::text)::uuid,"
            "'Legacy','ready',0,NULL,NULL,NULL "
            "FROM generate_series(1,100) n",
            (NS,),
        )
        database.execute("DELETE FROM session_observation_headers")
        database.execute("""CREATE FUNCTION slow_prepare() RETURNS trigger AS $$ BEGIN
            PERFORM pg_sleep(0.03); RETURN NEW; END; $$ LANGUAGE plpgsql""")
        database.execute(
            "CREATE TRIGGER slow_prepare AFTER INSERT ON session_observation_headers "
            "FOR EACH ROW EXECUTE FUNCTION slow_prepare()"
        )
    bounded = PostgresDatabase(dsn, deployment_namespace=NS)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        with bounded.connect_task_io(timeout_seconds=0.25) as database:
            prepare_session_observation_headers(database, deployment_namespace=NS, postgres=True)
    assert time.monotonic() - started < 0.7
    with psycopg.connect(dsn) as verify:
        assert verify.execute("SELECT COUNT(*) FROM session_observation_headers").fetchone() == (0,)
        assert verify.execute("SHOW statement_timeout").fetchone() == ("0",)


def test_full_schema_facade_and_old_export_are_body_free_and_read_only(postgres_dsn, tmp_path):
    from agent_storage import bootstrap_control_plane_epoch
    from agent_storage.postgres.agent_tasks import read_task_header as old_export
    from agent_storage.postgres.task_replay_headers import read_task_header

    from tests.agent_storage.test_postgres_agent_tasks import _seed_session

    assert old_export is read_task_header
    namespace, role = "gate-header-" + uuid4().hex, "gate_header_" + uuid4().hex
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
    sid = _seed_session(postgres_dsn, namespace, tmp_path, "Frozen title")
    task = TaskId(sid)
    store = PostgresAgentTaskStore(postgres_dsn, deployment_namespace=namespace)
    store.ensure_for_session(sid)
    assert store.backfill_event_positions(task)
    with psycopg.connect(postgres_dsn) as c:
        before = c.execute(
            "SELECT * FROM session_events WHERE deployment_namespace=%s ORDER BY sequence",
            (namespace,),
        ).fetchall()
        c.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'gate-header-test'").format(sql.Identifier(role))
        )
        c.execute(
            sql.SQL(
                "GRANT SELECT ON agent_tasks,session_observation_headers,"
                "agent_safety_overrides TO {}"
            ).format(sql.Identifier(role))
        )
    try:
        readonly = PostgresAgentTaskStore(
            make_conninfo(postgres_dsn, user=role, password="gate-header-test"),
            deployment_namespace=namespace,
        )
        header = readonly.read_task_header(task)
        assert header.title == "Frozen title"
        assert readonly.stream_head_reads_compatible
        with psycopg.connect(postgres_dsn) as c:
            assert (
                c.execute(
                    "SELECT * FROM session_events WHERE deployment_namespace=%s ORDER BY sequence",
                    (namespace,),
                ).fetchall()
                == before
            )
    finally:
        with psycopg.connect(postgres_dsn) as c:
            c.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            c.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
