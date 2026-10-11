"""Real scratch PG only: scalar DDL, resumable budgets, cold actual plans."""

import json
import os
import subprocess
import sys
import threading
import time
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_storage.postgres.task_replay_header_migration import TASK_REPLAY_HEADER_MIGRATION
from agent_storage.postgres.task_replay_headers import (
    HEADER_INDEXES,
    backfill_task_replay_headers,
    read_event_header,
    read_run_header,
)
from agent_storage.postgres.task_replay_scalar_header_migration import (
    TASK_REPLAY_SCALAR_HEADER_MIGRATION,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from tests.agent_storage.test_scalar_task_replay_headers import source_row

NS = "header-probe"


@pytest.fixture
def scratch():
    configured = os.environ.get("ZEBRA_HEADER_SCRATCH_DSN")
    if not configured:
        pytest.skip("set ZEBRA_HEADER_SCRATCH_DSN to the isolated header_scratch test container")
    settings = conninfo_to_dict(configured)
    assert settings.get("dbname") == "header_scratch"
    assert settings.get("host") in ("127.0.0.1", "localhost")
    schema = f"header_test_{uuid4().hex}"
    role = f"header_reader_{uuid4().hex}"
    with psycopg.connect(configured, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(configured, options=f"-c search_path={schema},public")
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            connection.execute("""CREATE TABLE session_events (
              deployment_namespace TEXT NOT NULL,event_id UUID NOT NULL,session_id UUID NOT NULL,
              sequence BIGINT NOT NULL,event_type TEXT NOT NULL,payload JSONB NOT NULL,
              actor TEXT NOT NULL,task_id UUID,task_sequence BIGINT,event_bytes_bound BIGINT,
              PRIMARY KEY(deployment_namespace,event_id),
              UNIQUE(deployment_namespace,session_id,sequence))""")
            connection.execute("""CREATE UNIQUE INDEX session_events_task_positions
              ON session_events(deployment_namespace,task_id,task_sequence)
              WHERE task_id IS NOT NULL""")
            connection.execute("""CREATE TABLE agent_tasks (
              deployment_namespace TEXT NOT NULL,task_id UUID NOT NULL,next_event_sequence BIGINT,
              event_position_state TEXT,PRIMARY KEY(deployment_namespace,task_id))""")
            connection.execute("""CREATE TABLE execution_segments (
              deployment_namespace TEXT NOT NULL,session_id UUID NOT NULL,task_id UUID NOT NULL,
              event_position_source_cursor BIGINT NOT NULL,
              event_position_source_ready BOOLEAN NOT NULL,
              PRIMARY KEY(deployment_namespace,session_id))""")
            for statement in HEADER_INDEXES:
                connection.execute(statement)
        yield dsn, role
    finally:
        # Drop only this generated scratch schema and role; never migrate/purge app DB.
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            if admin.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def install(connection):
    # Execute owned DDL in a newly created scratch schema, not the app migration catalog.
    for statement in TASK_REPLAY_SCALAR_HEADER_MIGRATION.statements:
        connection.execute(statement)


def seed(connection, task, rows, count):
    connection.execute("INSERT INTO agent_tasks VALUES (%s,%s,%s,'ready')", (NS, task, count))
    with connection.cursor().copy(
        "COPY session_events (deployment_namespace,event_id,session_id,sequence,event_type,"
        "payload,actor,task_id,task_sequence,event_bytes_bound) FROM STDIN"
    ) as copy:
        for row in rows:
            copy.write_row(
                (
                    NS,
                    UUID(row[0]),
                    UUID(row[1]),
                    row[2],
                    row[3],
                    Jsonb(json.loads(row[4])),
                    row[5],
                    UUID(row[6]),
                    row[7],
                    row[8],
                )
            )
    connection.execute(
        """INSERT INTO execution_segments
           SELECT deployment_namespace,session_id,task_id,MAX(sequence),true
           FROM session_events WHERE deployment_namespace=%s AND task_id=%s
           GROUP BY deployment_namespace,session_id,task_id""",
        (NS, task),
    )


def ready_count(connection):
    return connection.execute(
        "SELECT COUNT(*) AS n FROM session_events WHERE replay_header_ready"
    ).fetchone()["n"]


def test_pg62_checksum_is_unchanged():
    assert TASK_REPLAY_HEADER_MIGRATION.checksum == (
        "8d05945430613d43455b4d47850634d6e46cbdef841be55902b36bef316e5757"
    )


def test_real_pg_write_hooks_run_stopping_control_and_immutability(scratch):
    dsn, _ = scratch
    task = TaskId(uuid4())
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        install(connection)
        rows = [
            source_row(task, 0),
            source_row(task, 1, kind="resume", run=None, actor="harness", key="child-wakeup:"),
            source_row(
                task, 2, kind="resume", run=None, actor="harness", key="client-effect-resume:"
            ),
            source_row(task, 3, kind="cancel", run="control-only"),
            source_row(task, 4, kind="message", run=None),
            source_row(task, 5, body='{"kind":"run","payload":{"run_id":"not-command"}}'),
        ]
        seed(connection, task, rows, 6)
        assert ready_count(connection) == 6
        assert read_event_header(connection, NS, task, 1).internal_continuation
        assert read_event_header(connection, NS, task, 2).internal_continuation
        assert read_event_header(connection, NS, task, 5).command_kind is None
        assert read_run_header(connection, NS, task, "latest", None).stop == 4
        assert read_run_header(connection, NS, task, "latest", 3).stop is None
        assert read_run_header(connection, NS, task, "control-only", None).control_only
        for assignment in (
            "replay_run_id='forged'",
            "replay_header_ready=false",
            "actor='tool'",
            "event_type='session_created'",
            "payload='{}'",
        ):
            with pytest.raises(psycopg.Error, match="immutable"), connection.transaction():
                connection.execute(f"UPDATE session_events SET {assignment} WHERE task_sequence=0")
        with connection.cursor().copy(
            "COPY session_events (deployment_namespace,event_id,session_id,sequence,event_type,"
            "payload,actor,task_id,task_sequence,event_bytes_bound) FROM STDIN"
        ) as copy:
            row = source_row(task, 6)
            copy.write_row(
                (
                    NS,
                    UUID(row[0]),
                    task,
                    6,
                    row[3],
                    Jsonb(json.loads(row[4])),
                    row[5],
                    task,
                    6,
                    2048,
                )
            )
        connection.execute("UPDATE agent_tasks SET next_event_sequence=7")
        with pytest.raises(ValueError, match="ambiguous"):
            read_run_header(connection, NS, task, "latest", None)


def test_explicit_byte_and_row_budget_commit_and_reopen(scratch):
    dsn, _ = scratch
    task = TaskId(uuid4())
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        seed(connection, task, (source_row(task, n, source_bytes=2048) for n in range(600)), 600)
        install(connection)
        connection.commit()
        assert ready_count(connection) == 0
        with pytest.raises(CheckpointNotReady, match="explicit backfill"):
            read_run_header(connection, NS, task, "latest", None)
        assert not backfill_task_replay_headers(connection, NS, task, max_bytes=4096)
        assert ready_count(connection) == 2
        # Helper must not commit caller's transaction.
        with psycopg.connect(dsn, row_factory=dict_row) as observer:
            assert ready_count(observer) == 0
        connection.commit()
        assert not backfill_task_replay_headers(connection, NS, task)
        assert ready_count(connection) == 258
        connection.commit()
    with psycopg.connect(dsn, row_factory=dict_row) as recovered:
        assert ready_count(recovered) == 258
        assert not backfill_task_replay_headers(recovered, NS, task)
        assert ready_count(recovered) == 514
        assert backfill_task_replay_headers(recovered, NS, task)
        assert ready_count(recovered) == 600


@pytest.mark.parametrize("size,error", [(None, "byte bounds"), (2_000_000, "byte budget")])
def test_legacy_missing_bytes_or_oversize_fails_without_advancing(scratch, size, error):
    dsn, _ = scratch
    task = TaskId(uuid4())
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        seed(connection, task, [source_row(task, 0, source_bytes=size)], 1)
        install(connection)
        with pytest.raises(CheckpointNotReady, match=error):
            backfill_task_replay_headers(connection, NS, task)
        assert ready_count(connection) == 0


@pytest.mark.parametrize("external_cancel", [False, True])
def test_pg_deadline_or_real_cancel_rolls_back_batch_and_restores_gucs(scratch, external_cancel):
    dsn, _ = scratch
    task = TaskId(uuid4())
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        seed(connection, task, (source_row(task, n, source_bytes=2048) for n in range(100)), 100)
        install(connection)
        assert not backfill_task_replay_headers(connection, NS, task, limit=2)
        connection.commit()
        delay = 0.2 if external_cancel else 0.003
        connection.execute(f"""CREATE FUNCTION slow_header() RETURNS trigger AS $$ BEGIN
            PERFORM pg_sleep({delay}); RETURN NEW; END; $$ LANGUAGE plpgsql""")
        connection.execute("""CREATE TRIGGER slow_header AFTER UPDATE OF replay_header_ready
            ON session_events FOR EACH ROW EXECUTE FUNCTION slow_header()""")
        cancelled = threading.Event()

        def cancel_while_executing():
            with psycopg.connect(dsn, autocommit=True) as observer:
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    state = observer.execute(
                        "SELECT wait_event FROM pg_stat_activity WHERE pid=%s",
                        (connection.info.backend_pid,),
                    ).fetchone()
                    if state and state[0] == "PgSleep":
                        connection.cancel()
                        cancelled.set()
                        return
                    time.sleep(0.001)

        thread = threading.Thread(target=cancel_while_executing) if external_cancel else None
        if thread:
            thread.start()
        try:
            with pytest.raises(TimeoutError) as failure:
                backfill_task_replay_headers(
                    connection, NS, task, timeout_seconds=2 if external_cancel else 0.03
                )
        finally:
            if thread:
                thread.join(timeout=3)
                assert cancelled.is_set() and not thread.is_alive()
        if external_cancel:
            assert "due to user request" in str(failure.value.__cause__)
        assert ready_count(connection) == 2
        values = connection.execute(
            "SELECT current_setting('statement_timeout') AS s,current_setting('lock_timeout') AS l"
        ).fetchone()
        assert values == {"s": "0", "l": "0"}
        connection.execute("DROP TRIGGER slow_header ON session_events")
        assert backfill_task_replay_headers(connection, NS, task)


def test_pg_lock_deadline_is_bounded_and_readiness_uses_core_exception(scratch):
    dsn, _ = scratch
    task = TaskId(uuid4())
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        seed(connection, task, [source_row(task, 0, source_bytes=2048)], 1)
        install(connection)
        connection.commit()
        with pytest.raises(CheckpointNotReady):
            read_event_header(connection, NS, task, 0)
        with pytest.raises(ValueError) as invalid:
            read_event_header(connection, NS, task, True)
        assert not isinstance(invalid.value, CheckpointNotReady)
        with psycopg.connect(dsn) as blocker:
            blocker.execute("SELECT event_id FROM session_events FOR UPDATE")
            started = time.monotonic()
            with pytest.raises(TimeoutError):
                backfill_task_replay_headers(connection, NS, task, timeout_seconds=0.03)
            assert time.monotonic() - started < 0.5
            assert ready_count(connection) == 0
        assert backfill_task_replay_headers(connection, NS, task)
        connection.execute("UPDATE agent_tasks SET event_position_state='legacy'")
        with pytest.raises(ValueError) as invalid_run:
            read_run_header(connection, NS, task, "latest", True)
        assert not isinstance(invalid_run.value, CheckpointNotReady)
        with pytest.raises(CheckpointNotReady):
            read_event_header(connection, NS, task, 0)


def test_pg_header_helpers_preserve_caller_repeatable_read_snapshot(scratch):
    dsn, _ = scratch
    task = TaskId(uuid4())
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        install(connection)
        seed(connection, task, [source_row(task, 0)], 1)
    with psycopg.connect(dsn, row_factory=dict_row) as reader:
        reader.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        first = read_run_header(reader, NS, task, "latest", None)
        with psycopg.connect(dsn) as writer:
            row = source_row(task, 1, run="next")
            writer.execute(
                """INSERT INTO session_events
                (deployment_namespace,event_id,session_id,sequence,event_type,payload,actor,
                 task_id,task_sequence,event_bytes_bound) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    NS,
                    UUID(row[0]),
                    task,
                    row[2],
                    row[3],
                    Jsonb(json.loads(row[4])),
                    row[5],
                    task,
                    row[7],
                    row[8],
                ),
            )
            writer.execute("UPDATE agent_tasks SET next_event_sequence=2")
            writer.execute(
                "UPDATE execution_segments SET event_position_source_cursor=1 "
                "WHERE deployment_namespace=%s AND session_id=%s",
                (NS, task),
            )
        assert read_run_header(reader, NS, task, "latest", None) == first
        assert read_event_header(reader, NS, task, 1) is None
        reader.rollback()
        assert read_run_header(reader, NS, task, "latest", None).stop == 1


def plan_nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from plan_nodes(child)


@pytest.mark.parametrize("count", [1_000, 10_000, 100_000])
def test_cold_pg_seek_actual_rows_and_no_payload_privilege_with_huge_toast(scratch, count):
    dsn, role = scratch
    task = TaskId(uuid4())
    half = count // 2
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        install(connection)
        rows = (
            source_row(task, n, run=f"run-{n}")
            if n < half
            else source_row(task, n)
            if n == half
            else source_row(
                task, n, kind="cancel", run="control-only" if n == half + 1 else "latest"
            )
            for n in range(count - 1)
        )
        seed(connection, task, rows, count)
        huge = json.dumps({"output": "x" * (8 * 1024 * 1024)})
        row = source_row(task, count - 1, body=huge, source_bytes=len(huge) + 768)
        connection.execute(
            """INSERT INTO session_events
            (deployment_namespace,event_id,session_id,sequence,event_type,payload,actor,
             task_id,task_sequence,event_bytes_bound) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                NS,
                UUID(row[0]),
                task,
                row[2],
                row[3],
                Jsonb(json.loads(row[4])),
                row[5],
                task,
                row[7],
                row[8],
            ),
        )
        connection.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
        schema = connection.execute("SELECT current_schema() AS s").fetchone()["s"]
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            )
        )
        connection.execute(
            sql.SQL("""GRANT SELECT (deployment_namespace,task_id,task_sequence,
            event_id,session_id,sequence,event_type,replay_command_kind,replay_run_id,
            replay_internal_continuation,replay_header_ready) ON session_events TO {}""").format(
                sql.Identifier(role)
            )
        )
        connection.execute(
            sql.SQL("GRANT SELECT ON agent_tasks TO {}").format(sql.Identifier(role))
        )
        connection.execute(
            sql.SQL("GRANT SELECT ON execution_segments TO {}").format(sql.Identifier(role))
        )
        connection.execute(
            "UPDATE execution_segments SET event_position_source_cursor=%s "
            "WHERE deployment_namespace=%s AND session_id=%s",
            (count - 1, NS, task),
        )
        assert not connection.execute(
            "SELECT has_column_privilege(%s,'session_events','payload','SELECT') AS allowed",
            (role,),
        ).fetchone()["allowed"]
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("VACUUM ANALYZE session_events")
        connection.execute("ANALYZE agent_tasks")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.agent_storage.scalar_header_probe",
            "postgres",
            dsn,
            str(task),
            str(count),
            "--role",
            role,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    metrics = json.loads(result.stdout)
    assert metrics["decoded_body_bytes"] == 0
    visits = []
    for query in metrics["queries"]:
        nodes = list(plan_nodes(query["plan"]["Plan"]))
        # PostgreSQL may scan the single-row Task table; the historical source
        # must seek. PG heap tuples contain TOAST pointers, not the body itself.
        assert all(
            node["Node Type"] != "Seq Scan"
            for node in nodes
            if node.get("Relation Name") == "session_events"
        ), query
        assert all(node.get("Rows Removed by Filter", 0) == 0 for node in nodes)
        assert all(node.get("Actual Rows", 0) * node.get("Actual Loops", 0) <= 2 for node in nodes)
        assert "payload" not in json.dumps(query["plan"]).lower()
        scans = [node for node in nodes if "Scan" in node["Node Type"]]
        visits.extend(node["Actual Rows"] * node["Actual Loops"] for node in scans)
        assert all(
            node.get("Shared Hit Blocks", 0) + node.get("Shared Read Blocks", 0) < 32
            for node in scans
        ), query
    print(
        json.dumps(
            {
                "count": count,
                "max_actual_rows": max(visits),
                "cold_ms_including_explain": metrics["milliseconds_including_explain"],
                "decoded_body_bytes": 0,
            }
        )
    )
