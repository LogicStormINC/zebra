"""Real PostgreSQL checks; every test migrates only its own disposable database."""

from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import TaskId
from agent_storage.postgres import apply_postgres_migrations
from agent_storage.postgres.task_event_positions import (
    backfill_task_event_positions,
    repair_task_event_index,
)
from agent_storage.postgres.task_lineage import PostgresAgentTaskConflictError
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

NS = "position-quality"


@pytest.fixture
def positions_dsn() -> Generator[str]:
    configured = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not configured:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN with CREATEDB privilege")
    # Never migrate the configured/app database, even if the caller supplies it.
    admin_dsn = make_conninfo(configured, dbname="postgres")
    database = f"zebra_task_positions_quality_{uuid4().hex}"
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        dsn = make_conninfo(configured, dbname=database)
        apply_postgres_migrations(dsn)
        yield dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            # A failing deferred COMMIT can retain its connection in pytest's
            # traceback. This exact, independently created DB is disposable.
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


def _source(connection: psycopg.Connection[Any], count: int, namespace: str = NS) -> UUID:
    session = uuid4()
    connection.execute(
        "INSERT INTO session_streams VALUES (%s,%s,%s)", (namespace, session, count - 1)
    )
    connection.execute(
        """INSERT INTO session_projections
           (deployment_namespace,session_id,title,status,created_at,updated_at,current_sequence)
           VALUES (%s,%s,'test','created',now(),now(),%s)""",
        (namespace, session, count - 1),
    )
    connection.execute(
        """INSERT INTO session_events
           (deployment_namespace,event_id,session_id,sequence,event_type,payload,actor,created_at)
           SELECT %s,gen_random_uuid(),%s,n,'session_title_updated','{"title":"test"}',
                  'system',now() FROM generate_series(0,%s) n ORDER BY n""",
        (namespace, session, count - 1),
    )
    return session


def _coordinates(connection: psycopg.Connection[Any], session: UUID, positions: list[int]) -> None:
    for sequence, position in enumerate(positions):
        connection.execute(
            """UPDATE session_events SET task_id=%s,task_sequence=%s
               WHERE deployment_namespace=%s AND session_id=%s AND sequence=%s""",
            (session, position, NS, session, sequence),
        )


def _member(connection: psycopg.Connection[Any], root: UUID, *, namespace: str = NS) -> None:
    connection.execute(
        """INSERT INTO agent_tasks
           (deployment_namespace,task_id,root_session_id,active_segment_id,created_at,updated_at)
           VALUES (%s,%s,%s,%s,now(),now())""",
        (namespace, root, root, root),
    )
    connection.execute(
        """INSERT INTO execution_segments
           (deployment_namespace,session_id,task_id,segment_index,visibility)
           VALUES (%s,%s,%s,0,'internal')""",
        (namespace, root, root),
    )


def _seed(dsn: str, count: int, positions: list[int] | None = None) -> UUID:
    with psycopg.connect(dsn) as connection:
        root = _source(connection, count)
        if positions is not None:
            _coordinates(connection, root, positions)
    with psycopg.connect(dsn) as connection:
        _member(connection, root)
    return root


def _ready(dsn: str, count: int) -> UUID:
    with psycopg.connect(dsn) as connection:
        root = _source(connection, count)
        connection.execute(
            """UPDATE session_events SET task_id=%s,task_sequence=sequence
               WHERE deployment_namespace=%s AND session_id=%s""",
            (root, NS, root),
        )
    with psycopg.connect(dsn) as connection:
        _member(connection, root)
        connection.execute(
            """INSERT INTO task_event_index
               SELECT deployment_namespace,task_id,task_sequence,event_id,session_id,sequence
               FROM session_events WHERE deployment_namespace=%s AND task_id=%s""",
            (NS, root),
        )
        connection.execute(
            """UPDATE agent_tasks SET next_event_sequence=%s,event_position_state='ready'
               WHERE deployment_namespace=%s AND task_id=%s""",
            (count, NS, root),
        )
        connection.execute(
            """UPDATE execution_segments SET event_position_source_cursor=%s,
                      event_position_source_ready=true
               WHERE deployment_namespace=%s AND task_id=%s""",
            (count - 1, NS, root),
        )
    return root


def _append(connection: psycopg.Connection[Any], root: UUID) -> None:
    connection.execute(
        """INSERT INTO session_events
           (deployment_namespace,event_id,session_id,sequence,event_type,payload,actor,created_at)
           SELECT %s,gen_random_uuid(),%s,COALESCE(MAX(sequence)+1,0),
                  'session_title_updated','{"title":"late"}','system',now()
           FROM session_events WHERE deployment_namespace=%s AND session_id=%s""",
        (NS, root, NS, root),
    )


@pytest.mark.parametrize("positions", [[0, 2, 1], [0, 2, 3]])
def test_already_assigned_order_and_coverage_fail_closed(
    positions_dsn: str, positions: list[int]
) -> None:
    root = _seed(positions_dsn, 3, positions)
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        with pytest.raises(PostgresAgentTaskConflictError):
            backfill_task_event_positions(connection, NS, TaskId(root))


def test_foreign_positioned_child_is_not_skipped(positions_dsn: str) -> None:
    root = _seed(positions_dsn, 1)
    with psycopg.connect(positions_dsn) as connection:
        child = _source(connection, 1)
        _coordinates(connection, child, [0])
    with psycopg.connect(positions_dsn) as connection:
        connection.execute(
            """INSERT INTO execution_segments
               (deployment_namespace,session_id,task_id,predecessor_id,segment_index,
                visibility,rollover_reason) VALUES (%s,%s,%s,%s,1,'internal','recovery')""",
            (NS, child, root, root),
        )
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        with pytest.raises(PostgresAgentTaskConflictError, match="another Task"):
            backfill_task_event_positions(connection, NS, TaskId(root))


def test_source_backed_legacy_hole_is_adopted_without_renumbering(positions_dsn: str) -> None:
    root = _seed(positions_dsn, 3, [0, 1, 2])
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        assert backfill_task_event_positions(connection, NS, TaskId(root), limit=7)
        assert connection.execute("SELECT count(*) AS n FROM task_event_index").fetchone()["n"] == 3
        assert (
            connection.execute("SELECT next_event_sequence AS n FROM agent_tasks").fetchone()["n"]
            == 3
        )


def test_shared_budget_resumes_source_cursor_and_blocks_nonready_append(positions_dsn: str) -> None:
    root = _seed(positions_dsn, 600)
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        assert not backfill_task_event_positions(connection, NS, TaskId(root), limit=7)
        assert connection.execute("SELECT count(*) AS n FROM task_event_index").fetchone()["n"] == 7
        row = connection.execute("SELECT * FROM execution_segments").fetchone()
        assert row["event_position_source_cursor"] == 6
        assert not row["event_position_source_ready"]
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        with psycopg.connect(positions_dsn) as connection:
            _append(connection, root)
    for _ in range(4):
        with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
            done = backfill_task_event_positions(connection, NS, TaskId(root))
        if done:
            break
    assert done


@pytest.mark.parametrize("count", [1_000, 10_000, 100_000])
def test_clean_repair_seeks_bounded_candidates_before_filtering(
    positions_dsn: str, count: int
) -> None:
    from agent_storage.postgres.task_event_positions import _position_rows

    root = _ready(positions_dsn, count)
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:

        class MeasuredConnection:
            def execute(self, query: str, parameters: tuple[Any, ...]) -> Any:
                assert "payload" not in query
                plan = connection.execute(
                    "EXPLAIN (ANALYZE, FORMAT JSON) " + query, parameters
                ).fetchone()["QUERY PLAN"][0]["Plan"]
                pending = [plan]
                while pending:
                    node = pending.pop()
                    assert (node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node[
                        "Actual Loops"
                    ] <= 4, node
                    pending.extend(node.get("Plans", []))
                return connection.execute(query, parameters)

        assert len(_position_rows(MeasuredConnection(), NS, TaskId(root), -1, 1)) == 1
        assert repair_task_event_index(connection, NS, TaskId(root), limit=1) == 0
        row = connection.execute("SELECT * FROM agent_tasks").fetchone()
        assert row["event_index_repair_cursor"] == 0
        assert row["event_index_repair_highwater"] == count - 1


def test_repair_cycle_finishes_frozen_boundary_despite_appends(positions_dsn: str) -> None:
    root = _ready(positions_dsn, 4)
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        assert repair_task_event_index(connection, NS, TaskId(root), limit=1) == 0
        connection.execute("DELETE FROM task_event_index WHERE task_sequence=0")
    for _ in range(3):
        with psycopg.connect(positions_dsn) as connection:
            _append(connection, root)
        with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
            repair_task_event_index(connection, NS, TaskId(root), limit=1)
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        row = connection.execute("SELECT * FROM agent_tasks").fetchone()
        assert (row["event_index_repair_cursor"], row["event_index_repair_highwater"]) == (-1, -1)
        assert repair_task_event_index(connection, NS, TaskId(root), limit=1) == 1


def test_repair_detects_index_above_task_counter(positions_dsn: str) -> None:
    root = _seed(positions_dsn, 3, [0, 1])
    with psycopg.connect(positions_dsn) as connection:
        connection.execute(
            """INSERT INTO task_event_index SELECT deployment_namespace,%s,4,event_id,
                      session_id,sequence FROM session_events WHERE sequence=2""",
            (root,),
        )
        connection.execute(
            "UPDATE agent_tasks SET next_event_sequence=2,event_position_state='ready'"
        )
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        with pytest.raises(PostgresAgentTaskConflictError, match="highwater"):
            repair_task_event_index(connection, NS, TaskId(root), limit=1)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE task_event_index SET task_sequence=8 WHERE task_sequence=2",
        "DELETE FROM task_event_index",
    ],
)
def test_reservations_freeze_only_during_adoption(positions_dsn: str, mutation: str) -> None:
    root = _seed(positions_dsn, 3)
    with psycopg.connect(positions_dsn) as connection:
        connection.execute(
            """INSERT INTO task_event_index SELECT deployment_namespace,%s,sequence,event_id,
                      session_id,sequence FROM session_events ORDER BY sequence""",
            (root,),
        )
        # Legacy reservations remain editable before the first adoption batch.
        connection.execute("UPDATE task_event_index SET segment_sequence=segment_sequence")
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        assert not backfill_task_event_positions(connection, NS, TaskId(root), limit=1)
    with psycopg.connect(positions_dsn) as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(mutation)


@pytest.mark.parametrize("kind", ["prepositioned", "gap", "unallocated"])
def test_native_insert_and_assignment_guards(positions_dsn: str, kind: str) -> None:
    root = _ready(positions_dsn, 1)
    with psycopg.connect(positions_dsn) as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            if kind == "unallocated":
                _append(connection, root)
                connection.execute(
                    "UPDATE session_events SET task_id=%s,task_sequence=8 WHERE sequence=1", (root,)
                )
            else:
                connection.execute(
                    """INSERT INTO session_events
                       (deployment_namespace,event_id,session_id,sequence,event_type,payload,
                        actor,created_at,task_id,task_sequence)
                       VALUES (%s,gen_random_uuid(),%s,%s,'session_title_updated','{}',
                               'system',now(),%s,%s)""",
                    (
                        NS,
                        root,
                        2 if kind == "gap" else 1,
                        root if kind == "prepositioned" else None,
                        8 if kind == "prepositioned" else None,
                    ),
                )


def test_positioned_orphan_cannot_be_deleted_by_missing_membership(positions_dsn: str) -> None:
    with psycopg.connect(positions_dsn) as connection:
        root = _source(connection, 1)
        _coordinates(connection, root, [0])
    with psycopg.connect(positions_dsn) as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute("DELETE FROM session_events")


def test_namespace_cleanup_requires_explicit_authorization_and_decommission(
    positions_dsn: str,
) -> None:
    root = _ready(positions_dsn, 1)
    with psycopg.connect(positions_dsn) as connection:
        connection.execute(
            "SELECT set_config('zebra.task_source_cleanup_namespace',%s,true)", (NS,)
        )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute("DELETE FROM session_events")
    with psycopg.connect(positions_dsn) as connection:
        connection.execute("DELETE FROM agent_tasks")  # FK cascades decommission membership/index.
    with psycopg.connect(positions_dsn) as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute("DELETE FROM session_events")
    with psycopg.connect(positions_dsn) as connection:
        connection.execute("SELECT set_config('zebra.task_source_cleanup_namespace','other',true)")
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute("DELETE FROM session_events")
    with psycopg.connect(positions_dsn) as connection:
        connection.execute(
            "SELECT set_config('zebra.task_source_cleanup_namespace',%s,true)", (NS,)
        )
        connection.execute("DELETE FROM session_events WHERE task_id=%s", (root,))
        assert connection.execute("SELECT count(*) FROM session_events").fetchone() == (0,)


def test_import_restore_before_membership_deferred_commit_is_idempotent(positions_dsn: str) -> None:
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        root = _source(connection, 600)
        _coordinates(connection, root, list(range(256)))
        _member(connection, root)
        while not backfill_task_event_positions(connection, NS, TaskId(root)):
            pass  # ponytail: only this explicit offline full-snapshot import is unbounded.
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        assert (
            connection.execute("SELECT next_event_sequence AS n FROM agent_tasks").fetchone()["n"]
            == 600
        )
        assert (
            connection.execute("SELECT count(*) AS n FROM task_event_index").fetchone()["n"] == 600
        )


def test_deferred_allocator_waits_task61_after_source_locks(positions_dsn: str) -> None:
    root = _ready(positions_dsn, 1)
    with psycopg.connect(positions_dsn) as owner:
        owner.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,61))", (f"{NS}:{root}",))
        with psycopg.connect(positions_dsn) as writer:
            writer.execute("SET statement_timeout='3s'")
            writer.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"{NS}:{root}",)
            )
            _append(writer, root)  # INSERT does not take Task61 early.
            pid = writer.info.backend_pid
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(writer.commit)
                for _ in range(500):
                    owner.execute("SELECT pg_stat_clear_snapshot()")
                    if owner.execute(
                        "SELECT wait_event FROM pg_stat_activity WHERE pid=%s", (pid,)
                    ).fetchone() == ("advisory",):
                        break
                else:
                    pytest.fail("deferred allocator did not wait on Task61")
                owner.commit()
                future.result(timeout=4)


def test_assign_repairs_only_its_own_cell_within_shared_budget(positions_dsn: str) -> None:
    root = _seed(positions_dsn, 10, list(range(10)))
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        assert not backfill_task_event_positions(connection, NS, TaskId(root), limit=1)
        assert connection.execute("SELECT count(*) AS n FROM task_event_index").fetchone()["n"] == 1
        assert (
            connection.execute("SELECT event_position_cursor AS n FROM agent_tasks").fetchone()["n"]
            == 0
        )


def test_bounded_repair_validates_clean_candidates_then_conflicting_identity(
    positions_dsn: str,
) -> None:
    root = _ready(positions_dsn, 3)
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        connection.execute("UPDATE task_event_index SET segment_sequence=99 WHERE task_sequence=1")
        assert repair_task_event_index(connection, NS, TaskId(root), limit=1) == 0
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        with pytest.raises(PostgresAgentTaskConflictError, match="conflicts with source"):
            repair_task_event_index(connection, NS, TaskId(root), limit=1)


def test_native_guard_contender_does_not_wait_with_index_row_retained(positions_dsn: str) -> None:
    root = _ready(positions_dsn, 2)
    with psycopg.connect(positions_dsn) as owner:
        owner.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,61))", (f"{NS}:{root}",))
        with psycopg.connect(positions_dsn) as contender:
            contender.execute("SET statement_timeout='1s'")
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="busy"):
                contender.execute(
                    "UPDATE task_event_index SET segment_sequence=9 WHERE task_sequence=1"
                )
        # Contender's failed transaction has released its index row, not waited
        # for this owner's Task61 while retaining the row.
        owner.execute("UPDATE task_event_index SET segment_sequence=segment_sequence")


@pytest.mark.parametrize(
    "column,value",
    [
        ("task_sequence", "8"),
        ("task_id", "gen_random_uuid()"),
        ("sequence", "8"),
        ("event_id", "gen_random_uuid()"),
        ("session_id", "gen_random_uuid()"),
        ("deployment_namespace", "'other'"),
    ],
)
def test_bound_source_identity_and_coordinates_are_immutable(
    positions_dsn: str,
    column: str,
    value: str,
) -> None:
    _ready(positions_dsn, 1)
    with psycopg.connect(positions_dsn) as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable"):
            connection.execute(
                sql.SQL("UPDATE session_events SET {}={}").format(
                    sql.Identifier(column), sql.SQL(value)
                )
            )


def test_late_predecessor_keyed_retry_and_rollback_keep_positions(positions_dsn: str) -> None:
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.identifiers import SessionId
    from agent_storage import PostgresEventStore

    root = _ready(positions_dsn, 1)
    with psycopg.connect(positions_dsn) as connection:
        child = _source(connection, 1)
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        connection.execute(
            """INSERT INTO execution_segments
               (deployment_namespace,session_id,task_id,predecessor_id,segment_index,
                visibility,rollover_reason) VALUES (%s,%s,%s,%s,1,'internal','recovery')""",
            (NS, child, root, root),
        )
        assert backfill_task_event_positions(connection, NS, TaskId(root))
    store = PostgresEventStore(positions_dsn, deployment_namespace=NS)
    event = SessionEvent.create(
        session_id=SessionId(root),
        sequence=1,
        event_type=EventType.SESSION_TITLE_UPDATED,
        actor=EventActor.SYSTEM,
        payload={"title": "late metadata"},
        idempotency_key="late-A",
    )
    assert store.append(event) == event
    assert store.append(event) == event
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        _append(connection, root)
        connection.execute("SET CONSTRAINTS session_events_allocate_task_position IMMEDIATE")
        assert (
            connection.execute("SELECT next_event_sequence AS n FROM agent_tasks").fetchone()["n"]
            == 4
        )
        connection.rollback()
        rows = connection.execute(
            "SELECT session_id,sequence,task_sequence FROM session_events ORDER BY task_sequence"
        ).fetchall()
        assert [(row["session_id"], row["sequence"], row["task_sequence"]) for row in rows] == [
            (root, 0, 0),
            (child, 0, 1),
            (root, 1, 2),
        ]
        assert (
            connection.execute("SELECT next_event_sequence AS n FROM agent_tasks").fetchone()["n"]
            == 3
        )


def test_namespace_is_part_of_every_position_and_guard_lookup(positions_dsn: str) -> None:
    root = _ready(positions_dsn, 1)
    with psycopg.connect(positions_dsn) as connection:
        connection.execute("INSERT INTO session_streams VALUES ('other',%s,0)", (root,))
        connection.execute(
            """INSERT INTO session_projections
               (deployment_namespace,session_id,title,status,created_at,updated_at,current_sequence)
               VALUES ('other',%s,'other','created',now(),now(),0)""",
            (root,),
        )
        connection.execute(
            """INSERT INTO session_events
               (deployment_namespace,event_id,session_id,sequence,event_type,payload,actor,created_at)
               VALUES ('other',gen_random_uuid(),%s,0,
                       'session_title_updated','{}','system',now())""",
            (root,),
        )
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        _member(connection, root, namespace="other")
        assert backfill_task_event_positions(connection, "other", TaskId(root))
    with psycopg.connect(positions_dsn, row_factory=dict_row) as connection:
        assert repair_task_event_index(connection, NS, TaskId(root), limit=1) == 0
        rows = connection.execute("SELECT task_sequence FROM session_events").fetchall()
        assert [row["task_sequence"] for row in rows] == [0, 0]


def test_delete_guard_upgrade_replaces_existing_membership_only_trigger(positions_dsn: str) -> None:
    from agent_storage.postgres.task_event_position_guards import TASK_POSITION_GUARDS

    with psycopg.connect(positions_dsn) as connection:
        root = _source(connection, 1)
        _coordinates(connection, root, [0])
        connection.execute("DROP TRIGGER session_events_task_source_delete ON session_events")
        connection.execute("""CREATE FUNCTION old_member_only_delete() RETURNS trigger AS $$
            BEGIN
              IF EXISTS (SELECT 1 FROM execution_segments
                  WHERE deployment_namespace=OLD.deployment_namespace
                    AND session_id=OLD.session_id) THEN
                RAISE EXCEPTION 'immutable' USING ERRCODE='55000';
              END IF;
              RETURN OLD;
            END; $$ LANGUAGE plpgsql""")
        connection.execute("""CREATE TRIGGER session_events_task_source_delete
            BEFORE DELETE ON session_events FOR EACH ROW
            EXECUTE FUNCTION old_member_only_delete()""")
        for _ in range(2):
            for statement in TASK_POSITION_GUARDS:
                connection.execute(statement)
    with psycopg.connect(positions_dsn) as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable"):
            connection.execute("DELETE FROM session_events")


def test_cleanup_marker_without_database_owner_privilege_is_not_authority(
    positions_dsn: str,
) -> None:
    with psycopg.connect(positions_dsn) as connection:
        if not connection.execute(
            "SELECT rolsuper FROM pg_roles WHERE rolname=current_user"
        ).fetchone()[0]:
            pytest.skip("role impersonation check requires scratch administrator")
        root = _source(connection, 1)
        _coordinates(connection, root, [0])
        # Grant only this scratch table, not cluster-wide membership or privileges.
        connection.execute("GRANT DELETE ON session_events TO pg_read_all_data")
    with psycopg.connect(positions_dsn) as connection:
        connection.execute("SET LOCAL ROLE pg_read_all_data")
        connection.execute(
            "SELECT set_config('zebra.task_source_cleanup_namespace',%s,true)", (NS,)
        )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable"):
            connection.execute("DELETE FROM session_events")
