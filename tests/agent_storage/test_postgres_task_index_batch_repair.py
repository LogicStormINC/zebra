"""Bounded native repair proves each source/index mapping before set-oriented DML."""

import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import TaskId
from agent_storage.postgres import apply_postgres_migrations
from agent_storage.postgres.task_event_positions import (
    _position_rows,
    backfill_task_event_positions,
    repair_task_event_index,
)
from agent_storage.postgres.task_event_source_bounds_migration import BYTE_BOUND
from agent_storage.postgres.task_lineage import PostgresAgentTaskConflictError
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from tests.agent_storage.test_postgres_task_positions_quality import (
    NS,
    _append,
    _coordinates,
    _member,
    _ready,
    _source,
)


@pytest.fixture(scope="module")
def repair_dsn() -> Iterator[str]:
    configured = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not configured:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN for isolated native repair")
    schema = f"task_index_repair_{uuid4().hex}"
    with psycopg.connect(configured) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        dsn = make_conninfo(configured, options=f"-c search_path={schema}")
        apply_postgres_migrations(dsn)
        yield dsn
    finally:
        with psycopg.connect(configured) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


class MeasuredRepair:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.statements: list[str] = []
        self.changed_bounds: list[int] = []

    def execute(self, query: str, parameters: Any = ()) -> Any:
        self.statements.append(query)
        # Only native UPDATE evaluates JSON byte bounds; candidate proof returns
        # coordinates, never bodies. ARRAY inputs retain the page's hard bound.
        if query.lstrip().startswith("WITH candidates"):
            assert "payload" not in query
        for value in parameters:
            if isinstance(value, list):
                assert len(value) <= 256
        result = self.connection.execute(query, parameters)
        if query.startswith("UPDATE session_events SET event_bytes_bound="):
            assert "IS DISTINCT FROM" in query
            self.changed_bounds.append(result.rowcount)
        return result


@pytest.mark.parametrize("count", [1, 64, 256])
def test_clean_ready_repair_has_constant_sql_and_no_source_mutations(repair_dsn, count):
    root = _ready(repair_dsn, count)
    with psycopg.connect(repair_dsn, row_factory=dict_row) as connection:
        before = connection.execute(
            "SELECT event_id,xmin::text,task_sequence,event_bytes_bound FROM session_events "
            "WHERE deployment_namespace=%s AND task_id=%s ORDER BY task_sequence",
            (NS, root),
        ).fetchall()
        measured = MeasuredRepair(connection)
        assert repair_task_event_index(measured, NS, TaskId(root), limit=count) == 0
        assert len(measured.statements) == 7
        assert measured.changed_bounds == [0]
        after = connection.execute(
            "SELECT event_id,xmin::text,task_sequence,event_bytes_bound FROM session_events "
            "WHERE deployment_namespace=%s AND task_id=%s ORDER BY task_sequence",
            (NS, root),
        ).fetchall()
        assert after == before


def test_missing_mappings_repair_in_one_insert_without_renumbering(repair_dsn):
    root = _ready(repair_dsn, 256)
    with psycopg.connect(repair_dsn, row_factory=dict_row) as connection:
        before = connection.execute(
            "SELECT * FROM task_event_index WHERE deployment_namespace=%s AND task_id=%s "
            "ORDER BY task_sequence",
            (NS, root),
        ).fetchall()
        connection.execute(
            "DELETE FROM task_event_index WHERE deployment_namespace=%s AND task_id=%s "
            "AND task_sequence IN (0,17,255)",
            (NS, root),
        )
        measured = MeasuredRepair(connection)
        assert repair_task_event_index(measured, NS, TaskId(root)) == 3
        assert len(measured.statements) == 8
        assert sum("INSERT INTO task_event_index" in q for q in measured.statements) == 1
        assert (
            connection.execute(
                "SELECT * FROM task_event_index WHERE deployment_namespace=%s AND task_id=%s "
                "ORDER BY task_sequence",
                (NS, root),
            ).fetchall()
            == before
        )
        assert repair_task_event_index(connection, NS, TaskId(root)) == 0


def test_batch_proof_uses_bounded_native_seeks_not_history_scans(repair_dsn):
    root = _ready(repair_dsn, 1000)
    with psycopg.connect(repair_dsn, row_factory=dict_row) as connection:

        class PlanProbe:
            def execute(self, query: str, parameters: Any) -> Any:
                assert "payload" not in query
                plan = connection.execute(
                    "EXPLAIN (ANALYZE, FORMAT JSON) " + query,
                    parameters,
                ).fetchone()["QUERY PLAN"][0]["Plan"]
                pending = [plan]
                while pending:
                    node = pending.pop()
                    visits = node["Actual Rows"] + node.get("Rows Removed by Filter", 0)
                    assert visits * node["Actual Loops"] <= 8, (
                        node["Node Type"],
                        node.get("Index Name"),
                        node.get("Relation Name"),
                        node.get("Filter"),
                        node.get("Index Cond"),
                        visits,
                        node["Actual Loops"],
                    )
                    pending.extend(node.get("Plans", []))
                return connection.execute(query, parameters)

        assert (
            len(
                _position_rows(
                    PlanProbe(),
                    NS,
                    TaskId(root),
                    -1,
                    2,
                    highwater=999,
                    repair=True,
                )
            )
            == 2
        )


@pytest.mark.parametrize("damage", ["position", "segment", "sequence", "task", "event"])
def test_tampered_mapping_fails_before_any_batch_dml(repair_dsn, damage):
    root, foreign = _ready(repair_dsn, 4), _ready(repair_dsn, 1)
    with psycopg.connect(repair_dsn, row_factory=dict_row) as connection:
        child = None
        if damage == "segment":
            child = _source(connection, 1)
            connection.execute(
                """INSERT INTO execution_segments
                   (deployment_namespace,session_id,task_id,predecessor_id,segment_index,
                    visibility,rollover_reason) VALUES (%s,%s,%s,%s,1,'internal','recovery')""",
                (NS, child, root, root),
            )
            assert backfill_task_event_positions(connection, NS, TaskId(root))
        connection.execute(
            "DELETE FROM task_event_index WHERE deployment_namespace=%s AND task_id=%s "
            "AND task_sequence=0",
            (NS, root),
        )
        updates = {
            "position": ("task_sequence", 8),
            "segment": ("segment_id", child),
            "sequence": ("segment_sequence", 99),
            "task": ("task_id", foreign),
        }
        if damage == "event":
            column, value = (
                "event_id",
                connection.execute(
                    "DELETE FROM task_event_index WHERE deployment_namespace=%s AND task_id=%s "
                    "RETURNING event_id",
                    (NS, foreign),
                ).fetchone()["event_id"],
            )
        else:
            column, value = updates[damage]
        if damage == "task":
            connection.execute(
                "UPDATE task_event_index SET task_id=%s,segment_id=%s "
                "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence=2",
                (foreign, foreign, NS, root),
            )
        else:
            connection.execute(
                sql.SQL(
                    "UPDATE task_event_index SET {}=%s WHERE deployment_namespace=%s "
                    "AND task_id=%s AND task_sequence=2"
                ).format(sql.Identifier(column)),
                (value, NS, root),
            )
    with psycopg.connect(repair_dsn, row_factory=dict_row) as connection:
        measured = MeasuredRepair(connection)
        with pytest.raises(PostgresAgentTaskConflictError, match="conflicts with source"):
            repair_task_event_index(measured, NS, TaskId(root))
        assert not measured.changed_bounds
        assert not any("INSERT INTO task_event_index" in q for q in measured.statements)
        assert (
            connection.execute(
                "SELECT 1 FROM task_event_index WHERE deployment_namespace=%s AND task_id=%s "
                "AND task_sequence=0",
                (NS, root),
            ).fetchone()
            is None
        )


def test_bounded_cycle_revisits_deleted_prefix_despite_appends(repair_dsn):
    root = _ready(repair_dsn, 4)
    with psycopg.connect(repair_dsn, row_factory=dict_row) as connection:
        assert repair_task_event_index(connection, NS, TaskId(root), limit=1) == 0
        connection.execute(
            "DELETE FROM task_event_index WHERE deployment_namespace=%s AND task_id=%s "
            "AND task_sequence=0",
            (NS, root),
        )
    for _ in range(3):
        with psycopg.connect(repair_dsn, row_factory=dict_row) as connection:
            _append(connection, root)
            assert repair_task_event_index(connection, NS, TaskId(root), limit=1) == 0
    with psycopg.connect(repair_dsn, row_factory=dict_row) as connection:
        checkpoint = connection.execute(
            "SELECT event_index_repair_cursor,event_index_repair_highwater FROM agent_tasks "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (NS, root),
        ).fetchone()
        assert tuple(checkpoint.values()) == (-1, -1)
        assert repair_task_event_index(connection, NS, TaskId(root), limit=1) == 1


@pytest.mark.parametrize("damage", ["missing", "foreign", "inverted"])
def test_ready_repair_checks_source_predecessor_outside_page(repair_dsn, damage):
    root = _ready(repair_dsn, 3)
    with psycopg.connect(repair_dsn) as connection:
        # Fault injection is confined to this disposable schema; native production
        # source guards remain installed and unchanged by the implementation.
        connection.execute("ALTER TABLE session_events DISABLE TRIGGER USER")
        try:
            if damage == "missing":
                connection.execute(
                    "DELETE FROM task_event_index WHERE deployment_namespace=%s AND task_id=%s "
                    "AND task_sequence=0",
                    (NS, root),
                )
                connection.execute(
                    "DELETE FROM session_events WHERE deployment_namespace=%s AND task_id=%s "
                    "AND sequence=0",
                    (NS, root),
                )
            elif damage == "foreign":
                connection.execute(
                    "UPDATE session_events SET task_id=%s WHERE deployment_namespace=%s "
                    "AND task_id=%s AND sequence=0",
                    (uuid4(), NS, root),
                )
            else:
                connection.execute(
                    "UPDATE session_events SET task_sequence=8 WHERE deployment_namespace=%s "
                    "AND task_id=%s AND sequence=2",
                    (NS, root),
                )
                connection.execute(
                    "UPDATE session_events SET task_sequence=2 WHERE deployment_namespace=%s "
                    "AND task_id=%s AND sequence=0",
                    (NS, root),
                )
                connection.execute(
                    "UPDATE session_events SET task_sequence=0 WHERE deployment_namespace=%s "
                    "AND task_id=%s AND sequence=2",
                    (NS, root),
                )
        finally:
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
            connection.execute("ALTER TABLE session_events ENABLE TRIGGER USER")
        connection.execute(
            "UPDATE agent_tasks SET event_index_repair_cursor=0,event_index_repair_highwater=2 "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (NS, root),
        )
    message = {
        "missing": "omits a source prefix",
        "foreign": "another Task",
        "inverted": "invert source order",
    }[damage]
    with psycopg.connect(repair_dsn, row_factory=dict_row) as connection:
        with pytest.raises(PostgresAgentTaskConflictError, match=message):
            repair_task_event_index(connection, NS, TaskId(root), limit=1)


def test_byte_bound_repair_is_bounded_and_retains_native_sealed_guard(repair_dsn):
    with psycopg.connect(repair_dsn) as connection:
        root = uuid4()
        connection.execute("INSERT INTO session_streams VALUES (%s,%s,2)", (NS, root))
        connection.execute(
            """INSERT INTO session_projections
               (deployment_namespace,session_id,title,status,created_at,updated_at,current_sequence)
               VALUES (%s,%s,'sealed','created',now(),now(),2)""",
            (NS, root),
        )
        # Storage-only accepted source, not qualification of an execution proof.
        # Construct it through the real INSERT guards rather than rewrite a body.
        connection.execute(
            """INSERT INTO session_events
               (deployment_namespace,event_id,session_id,sequence,event_type,payload,actor,created_at)
               SELECT %s,gen_random_uuid(),%s,n,
                 CASE WHEN n=0 THEN 'coverage_batch_accepted' ELSE 'session_title_updated' END,
                 CASE WHEN n=0 THEN jsonb_build_object('namespace',%s::text,'run_id',%s::text)
                   ELSE '{"title":"test"}'::jsonb END,'system',now()
               FROM generate_series(0,2) n ORDER BY n""",
            (NS, root, NS, str(root)),
        )
        _coordinates(connection, root, [0, 1, 2])
    with psycopg.connect(repair_dsn, row_factory=dict_row) as connection:
        _member(connection, root)
        assert backfill_task_event_positions(connection, NS, TaskId(root))
        connection.execute(
            """INSERT INTO coverage_execution_receipts
               (deployment_namespace,namespace,run_id,session_id,event_id,sequence,body,body_digest)
               SELECT deployment_namespace,%s,%s,session_id,event_id,sequence,
                 '{"protocol":"coverage-execution-receipt/1"}'::jsonb,repeat('a',64)
               FROM session_events WHERE deployment_namespace=%s AND task_id=%s AND sequence=0""",
            (NS, str(root), NS, root),
        )
        # A clean sealed row must not receive even a no-op UPDATE.
        measured = MeasuredRepair(connection)
        assert repair_task_event_index(measured, NS, TaskId(root)) == 0
        assert measured.changed_bounds == [0]
        with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
            with connection.transaction():
                connection.execute(
                    "UPDATE session_events SET event_bytes_bound=event_bytes_bound "
                    "WHERE deployment_namespace=%s AND task_id=%s AND sequence=0",
                    (NS, root),
                )
        connection.execute("ALTER TABLE session_events DISABLE TRIGGER session_events_byte_bound")
        connection.execute(
            "UPDATE session_events SET event_bytes_bound=1 WHERE deployment_namespace=%s "
            "AND task_id=%s AND sequence>0",
            (NS, root),
        )
        connection.execute("ALTER TABLE session_events ENABLE TRIGGER session_events_byte_bound")
        assert repair_task_event_index(connection, NS, TaskId(root), limit=2) == 0
        assert connection.execute(
            f"SELECT sequence,event_bytes_bound=({BYTE_BOUND}) AS valid FROM session_events "
            "WHERE deployment_namespace=%s AND task_id=%s ORDER BY sequence",
            (NS, root),
        ).fetchall() == [
            {"sequence": 0, "valid": True},
            {"sequence": 1, "valid": True},
            {"sequence": 2, "valid": False},
        ]
        # A corrupt bound on a sealed source must still refuse, not acquire a
        # caller-specific repair exemption. Roll back this schema-only injection.
        with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
            with connection.transaction():
                connection.execute(
                    "ALTER TABLE session_events DISABLE TRIGGER coverage_execution_source_retention"
                )
                connection.execute(
                    "ALTER TABLE session_events DISABLE TRIGGER session_events_byte_bound"
                )
                connection.execute(
                    "UPDATE session_events SET event_bytes_bound=1 WHERE deployment_namespace=%s "
                    "AND task_id=%s AND sequence=0",
                    (NS, root),
                )
                connection.execute(
                    "ALTER TABLE session_events ENABLE TRIGGER coverage_execution_source_retention"
                )
                connection.execute(
                    "ALTER TABLE session_events ENABLE TRIGGER session_events_byte_bound"
                )
                connection.execute(
                    "UPDATE agent_tasks SET event_index_repair_cursor=-1,"
                    "event_index_repair_highwater=-1 WHERE deployment_namespace=%s AND task_id=%s",
                    (NS, root),
                )
                repair_task_event_index(connection, NS, TaskId(root), limit=1)


def test_set_repair_rolls_back_mappings_and_cursor(repair_dsn):
    root = _ready(repair_dsn, 3)
    with psycopg.connect(repair_dsn) as connection:
        connection.execute(
            "DELETE FROM task_event_index WHERE deployment_namespace=%s AND task_id=%s",
            (NS, root),
        )
    with psycopg.connect(repair_dsn, row_factory=dict_row) as connection:
        assert repair_task_event_index(connection, NS, TaskId(root)) == 3
        connection.rollback()
        assert (
            connection.execute(
                "SELECT 1 FROM task_event_index WHERE deployment_namespace=%s AND task_id=%s",
                (NS, root),
            ).fetchone()
            is None
        )
        assert (
            connection.execute(
                "SELECT event_index_repair_cursor FROM agent_tasks WHERE deployment_namespace=%s "
                "AND task_id=%s",
                (NS, root),
            ).fetchone()["event_index_repair_cursor"]
            == -1
        )
