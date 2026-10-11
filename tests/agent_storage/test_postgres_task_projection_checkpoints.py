"""Independent real PG checks for the derived-only checkpoint mixin."""

from __future__ import annotations

import os
from collections.abc import Callable, Generator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionCell,
    ProjectionCellKey,
    ProjectionCheckpointHead,
    ProjectionFrameHeader,
    ProjectionScope,
    ProjectionTransition,
    SegmentCheckpoint,
)
from agent_storage.postgres import apply_postgres_migrations
from agent_storage.postgres.database import PostgresDatabase
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

NS = "checkpoint-quality"
TABLES = ("heads", "frames", "scalars", "cells")


@pytest.fixture
def checkpoint_dsn() -> Generator[str]:
    configured = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not configured:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN with CREATEDB privilege")
    from agent_storage.postgres.task_projection_checkpoints_migration import (
        TASK_PROJECTION_CHECKPOINTS_MIGRATION,
    )

    admin_dsn = make_conninfo(configured, dbname="postgres")
    name = f"zebra_task_checkpoints_{uuid4().hex}"
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        dsn = make_conninfo(configured, dbname=name)
        apply_postgres_migrations(dsn)
        with psycopg.connect(dsn) as connection:
            applied = connection.execute(
                "SELECT name,checksum FROM zebra_schema_migrations WHERE version=64"
            ).fetchone()
            migration = TASK_PROJECTION_CHECKPOINTS_MIGRATION
            if applied is None:  # Parent owns catalog registration, not this lane.
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO zebra_schema_migrations(version,name,checksum) VALUES (%s,%s,%s)",
                    (migration.version, migration.name, migration.checksum),
                )
            else:
                assert applied == (migration.name, migration.checksum)
        yield dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _store(dsn: str, namespace: str = NS) -> Any:
    from agent_storage.postgres.task_projection_checkpoints import (
        PostgresTaskProjectionCheckpointMixin,
    )

    class Store(PostgresTaskProjectionCheckpointMixin):
        def __init__(self) -> None:
            self._database = PostgresDatabase(dsn, deployment_namespace=namespace)

    return Store()


def _seed(dsn: str, count: int = 3) -> tuple[ProjectionScope, tuple[dict[str, Any], ...]]:
    root = uuid4()
    with psycopg.connect(dsn) as connection:
        connection.execute("INSERT INTO session_streams VALUES (%s,%s,%s)", (NS, root, count - 1))
        connection.execute(
            """INSERT INTO session_projections
               (deployment_namespace,session_id,title,status,created_at,updated_at,current_sequence)
               VALUES (%s,%s,'checkpoint','created',now(),now(),%s)""",
            (NS, root, count - 1),
        )
        created = datetime.now(UTC)
        for start in range(0, count, 256):
            stop = min(start + 256, count)
            with (
                connection.cursor() as cursor,
                cursor.copy(
                    """COPY session_events
                   (deployment_namespace,event_id,session_id,sequence,event_type,payload,
                    actor,created_at) FROM STDIN"""
                ) as bulk,
            ):
                for position in range(start, stop):
                    bulk.write_row(
                        (
                            NS,
                            uuid4(),
                            root,
                            position,
                            "session_title_updated",
                            '{"title":"seed"}',
                            "system",
                            created,
                        )
                    )
            connection.execute(
                """UPDATE session_events SET task_id=%s,task_sequence=sequence
                   WHERE deployment_namespace=%s AND session_id=%s
                     AND sequence>=%s AND sequence<%s""",
                (root, NS, root, start, stop),
            )
            connection.commit()  # Bound deferred source-trigger work before membership exists.
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        connection.execute(
            """INSERT INTO agent_tasks
               (deployment_namespace,task_id,root_session_id,active_segment_id,created_at,updated_at,
                next_event_sequence,event_position_state)
               VALUES (%s,%s,%s,%s,now(),now(),%s,'ready')""",
            (NS, root, root, root, count),
        )
        connection.execute(
            """INSERT INTO execution_segments
               (deployment_namespace,session_id,task_id,segment_index,visibility,
                event_position_source_cursor,event_position_source_ready)
               VALUES (%s,%s,%s,0,'internal',%s,true)""",
            (NS, root, root, count - 1),
        )
        rows = tuple(
            connection.execute(
                """SELECT task_sequence,event_id,session_id,sequence FROM session_events
                   WHERE deployment_namespace=%s AND task_id=%s
                   ORDER BY task_sequence LIMIT 256""",
                (NS, root),
            ).fetchall()
        )
    return ProjectionScope(NS, TaskId(root), None, "ag-ui-v1"), rows


def _page(
    scope: ProjectionScope,
    rows: tuple[dict[str, Any], ...],
    start: int,
    stop: int,
    *,
    cells: tuple[ProjectionCell, ...] = (),
    terminal: int | None = None,
) -> ProjectionTransition:
    headers = tuple(
        ProjectionFrameHeader(
            row["task_sequence"],
            EventId(row["event_id"]),
            SessionId(row["session_id"]),
            row["sequence"],
            row["task_sequence"] - 1,
            1,
            True,
            True,
        )
        for row in rows[start:stop]
    )
    scalars = tuple(
        SegmentCheckpoint(
            header.segment_id,
            header.task_sequence,
            header.segment_sequence,
            True,
            header.task_sequence == terminal,
        )
        for header in headers
    )
    return ProjectionTransition(scope, start - 1, headers, scalars, cells, terminal)


def _key(scope: ProjectionScope, name: str = "call") -> ProjectionCellKey:
    return ProjectionCellKey(SessionId(scope.task_id), "tool_call", name)


def _counts(dsn: str) -> tuple[int, ...]:
    with psycopg.connect(dsn) as connection:
        result = []
        for table in TABLES:
            row = connection.execute(
                sql.SQL("SELECT count(*) FROM {}").format(
                    sql.Identifier(f"task_projection_{table}")
                )
            ).fetchone()
            assert row is not None
            result.append(row[0])
        return tuple(result)


def test_missing_head_reads_are_initial_observations_without_dml(checkpoint_dsn: str) -> None:
    scope, _ = _seed(checkpoint_dsn)
    store = _store(checkpoint_dsn)
    assert store.read_checkpoint_head(scope) == ProjectionCheckpointHead(scope)
    assert store.read_segment_checkpoint_before(scope, SessionId(scope.task_id), 0) == (
        SegmentCheckpoint(SessionId(scope.task_id), -1, -1, False, False)
    )
    assert store.read_cells_at(scope, 0, (_key(scope),)) == ()
    assert _counts(checkpoint_dsn) == (0, 0, 0, 0)
    with pytest.raises(CheckpointNotReady):
        store.read_event_projection_header(scope, 0)
    with pytest.raises(CheckpointNotReady):
        store.read_cells_at(scope, 1, ())


def test_exact_strict_before_tombstones_and_head_locators(checkpoint_dsn: str) -> None:
    scope, rows = _seed(checkpoint_dsn)
    store, key = _store(checkpoint_dsn), _key(scope)
    first = _page(scope, rows, 0, 1, cells=(ProjectionCell(key, 0, "1"),))
    store.commit_projection_page(first)
    assert store.read_cells_at(scope, 0, (key,)) == ()
    assert store.read_cells_at(scope, 1, (key,)) == first.cells
    store.commit_projection_page(
        _page(scope, rows, 1, 2, cells=(ProjectionCell(key, 1, None),), terminal=1)
    )
    assert store.read_cells_at(scope, 1, (key,)) == first.cells
    assert store.read_cells_at(scope, 2, (key,))[0].value is None
    assert store.read_segment_checkpoint_before(scope, key.segment_id, 1) == first.scalars[0]
    store.commit_projection_page(_page(scope, rows, 2, 3))
    head = store.read_checkpoint_head(scope)
    assert head.through_sequence == 2 and head.last_event_id == rows[2]["event_id"]
    assert head.latest_eligible.task_sequence == 2 and head.terminal.task_sequence == 1
    assert _counts(checkpoint_dsn) == (1, 3, 3, 2)


@pytest.mark.parametrize("bad", ["namespace", "missing_task", "foreign_anchor", "unready"])
def test_namespace_and_canonical_source_anchor_gate(checkpoint_dsn: str, bad: str) -> None:
    scope, _ = _seed(checkpoint_dsn)
    if bad == "namespace":
        scope = replace(scope, namespace="foreign")
    elif bad == "missing_task":
        scope = replace(scope, task_id=TaskId(uuid4()))
    elif bad == "foreign_anchor":
        scope = replace(scope, anchor_event_id=EventId(uuid4()))
    else:
        with psycopg.connect(checkpoint_dsn) as connection:
            connection.execute("UPDATE agent_tasks SET event_position_state='assigning'")
    with pytest.raises(CheckpointConflict if bad != "unready" else CheckpointNotReady):
        _store(checkpoint_dsn).read_checkpoint_head(scope)
    assert _counts(checkpoint_dsn) == (0, 0, 0, 0)


def test_anchor_and_projector_version_are_disjoint_scopes(checkpoint_dsn: str) -> None:
    scope, rows = _seed(checkpoint_dsn)
    store = _store(checkpoint_dsn)
    anchored = replace(scope, anchor_event_id=EventId(rows[0]["event_id"]))
    versioned = replace(scope, projector_version="ag-ui-v2")
    for owned in (scope, anchored, versioned):
        store.commit_projection_page(_page(owned, rows, 0, 1))
    assert _counts(checkpoint_dsn) == (3, 3, 3, 0)
    assert (
        store.read_checkpoint_head(replace(anchored, projector_version="ag-ui-v2")).through_sequence
        == -1
    )


@pytest.mark.parametrize("before", [-1, True, 1.5, 9_223_372_036_854_775_808])
def test_strict_position_bounds(checkpoint_dsn: str, before: Any) -> None:
    scope, _ = _seed(checkpoint_dsn)
    store = _store(checkpoint_dsn)
    with pytest.raises(ValueError):
        store.read_segment_checkpoint_before(scope, SessionId(scope.task_id), before)
    with pytest.raises(ValueError):
        store.read_cells_at(scope, before, ())
    with pytest.raises(ValueError):
        store.read_event_projection_header(scope, before)


def test_key_request_count_duplicates_and_bytes_are_admitted_before_queries(
    checkpoint_dsn: str,
) -> None:
    scope, _ = _seed(checkpoint_dsn)
    store, key = _store(checkpoint_dsn), _key(scope)
    for keys in (
        (key, key),
        tuple(replace(key, key=str(i)) for i in range(1025)),
        tuple(replace(key, key=str(i) + "x" * 1000) for i in range(1024)),
    ):
        with pytest.raises(ValueError):
            store.read_cells_at(scope, 0, keys)
    with pytest.raises(CheckpointConflict):
        store.read_cells_at(scope, 0, (replace(key, segment_id=SessionId(uuid4())),))


def test_cell_metadata_byte_admission_is_all_or_error(checkpoint_dsn: str) -> None:
    scope, rows = _seed(checkpoint_dsn)
    store = _store(checkpoint_dsn)
    keys = tuple(
        ProjectionCellKey(SessionId(scope.task_id), "text_message", str(i)) for i in range(160)
    )
    for position in range(2):
        cells = tuple(
            ProjectionCell(key, position, "v" * 2048)
            for key in keys[position * 80 : (position + 1) * 80]
        )
        store.commit_projection_page(_page(scope, rows, position, position + 1, cells=cells))
    assert len(store.read_cells_at(scope, 2, keys[:80])) == 80
    with pytest.raises(ValueError, match="byte bound"):
        store.read_cells_at(scope, 2, keys)


@pytest.mark.parametrize("fault", ["growth", "mismatched_value"])
def test_cell_value_cannot_bypass_admitted_metadata(
    checkpoint_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    scope, rows = _seed(checkpoint_dsn)
    store = _store(checkpoint_dsn)
    key = replace(_key(scope), kind="text_message")
    store.commit_projection_page(_page(scope, rows, 0, 1, cells=(ProjectionCell(key, 0, "v"),)))
    changed, loaded_values = False, 0

    def admitted_rows(cursor: psycopg.Cursor[Any]) -> Callable[[Sequence[Any]], dict[str, Any]]:
        make_row = dict_row(cursor)

        def materialize(values: Sequence[Any]) -> dict[str, Any]:
            nonlocal changed, loaded_values
            row = make_row(values)
            if fault == "growth" and "byte_count" in row and not changed:
                changed = True
                with psycopg.connect(checkpoint_dsn) as writer:
                    writer.execute(
                        """UPDATE task_projection_cells SET value=%s,byte_count=%s
                           WHERE deployment_namespace=%s AND task_id=%s""",
                        ("v" * 2048, 256 + 6 * len(key.key) + 6 * 2048, NS, scope.task_id),
                    )
            if "value" in row:
                loaded_values += 1
                if fault == "mismatched_value":
                    row["value"] += "x"  # Fault injection after a real indexed value fetch.
            return row

        return materialize

    monkeypatch.setattr(
        store._database,
        "connect_task_io",
        lambda: psycopg.connect(checkpoint_dsn, row_factory=admitted_rows),
    )
    if fault == "growth":
        # A concurrent writer is outside this RR snapshot: never mix its new
        # value with the previously admitted metadata, nor require a false conflict.
        assert store.read_cells_at(scope, 1, (key,)) == (ProjectionCell(key, 0, "v"),)
        assert changed and loaded_values == 1
        assert store.read_cells_at(scope, 1, (key,)) == (ProjectionCell(key, 0, "v" * 2048),)
        # Stored value/byte-count mismatch must fail at the native constraint;
        # the mismatched_value case separately verifies the reader's guard.
        with pytest.raises(psycopg.errors.CheckViolation, match="task_projection_cells"):
            with psycopg.connect(checkpoint_dsn) as writer:
                writer.execute(
                    """UPDATE task_projection_cells SET byte_count=byte_count-1
                       WHERE deployment_namespace=%s AND task_id=%s""",
                    (NS, scope.task_id),
                )
        assert store.read_cells_at(scope, 1, (key,)) == (ProjectionCell(key, 0, "v" * 2048),)
        return
    with pytest.raises(CheckpointConflict, match="changed|metadata conflicts"):
        store.read_cells_at(scope, 1, (key,))
    assert loaded_values == 1


@pytest.mark.parametrize("previous_sequence", [1, 99])
def test_existing_scalar_source_sequence_must_strictly_precede_next_event(
    checkpoint_dsn: str,
    previous_sequence: int,
) -> None:
    scope, rows = _seed(checkpoint_dsn)
    store = _store(checkpoint_dsn)
    store.commit_projection_page(_page(scope, rows, 0, 1))
    with psycopg.connect(checkpoint_dsn) as connection:
        connection.execute(
            "UPDATE task_projection_scalars SET segment_sequence=%s",
            (previous_sequence,),
        )
    counts = _counts(checkpoint_dsn)
    # The source-identity guard may reject the corrupt scalar before the later
    # strict predecessor-order guard. Both are the same typed, atomic contract.
    with pytest.raises(CheckpointConflict, match="predecessor|canonical source"):
        store.commit_projection_page(_page(scope, rows, 1, 2))
    assert _counts(checkpoint_dsn) == counts
    assert store.read_checkpoint_head(scope).through_sequence == 0


def test_cas_conflict_publishes_nothing_and_never_overwrites(checkpoint_dsn: str) -> None:
    scope, rows = _seed(checkpoint_dsn)
    store = _store(checkpoint_dsn)
    page = _page(scope, rows, 0, 2, cells=(ProjectionCell(_key(scope), 1, "1"),))
    expected = store.commit_projection_page(page)
    counts = _counts(checkpoint_dsn)
    with pytest.raises(CheckpointConflict, match="CAS"):
        store.commit_projection_page(page)
    assert _counts(checkpoint_dsn) == counts
    assert store.read_checkpoint_head(scope) == expected


@pytest.mark.parametrize("bad", ["event", "segment", "segment_sequence", "predecessor", "coverage"])
def test_source_and_scalar_predecessor_conflicts_roll_back_missing_head(
    checkpoint_dsn: str,
    bad: str,
) -> None:
    scope, rows = _seed(checkpoint_dsn)
    page = _page(scope, rows, 0, 2)
    second = page.headers[1]
    if bad == "event":
        second = replace(second, event_id=EventId(uuid4()))
    elif bad == "segment":
        second = replace(second, segment_id=SessionId(uuid4()))
    elif bad == "segment_sequence":
        second = replace(second, segment_sequence=99)
    elif bad == "predecessor":
        second = replace(second, state_before_sequence=-1)
    else:
        with psycopg.connect(checkpoint_dsn) as connection:
            connection.execute("UPDATE agent_tasks SET next_event_sequence=1")
    scalar = replace(
        page.scalars[1], segment_id=second.segment_id, segment_sequence=second.segment_sequence
    )
    page = replace(page, headers=(page.headers[0], second), scalars=(page.scalars[0], scalar))
    with pytest.raises(CheckpointConflict):
        _store(checkpoint_dsn).commit_projection_page(page)
    assert _counts(checkpoint_dsn) == (0, 0, 0, 0)


def test_existing_scalar_predecessor_and_unprojected_gaps(checkpoint_dsn: str) -> None:
    scope, rows = _seed(checkpoint_dsn, 4)
    store = _store(checkpoint_dsn)
    store.commit_projection_page(_page(scope, rows, 0, 1))
    skipped = replace(
        _page(scope, rows, 1, 2).headers[0],
        projected=False,
        eligible=False,
        frame_count=0,
        state_before_sequence=-1,
    )
    store.commit_projection_page(ProjectionTransition(scope, 0, (skipped,), (), ()))
    page = _page(scope, rows, 2, 3)
    with pytest.raises(CheckpointConflict, match="predecessor"):
        store.commit_projection_page(page)
    assert store.read_checkpoint_head(scope).through_sequence == 1
    header = replace(page.headers[0], state_before_sequence=0)
    store.commit_projection_page(replace(page, headers=(header,)))
    assert store.read_segment_checkpoint_before(scope, header.segment_id, 3).task_sequence == 2


def test_database_failure_after_inserts_rolls_back_all_rows(checkpoint_dsn: str) -> None:
    scope, rows = _seed(checkpoint_dsn)
    with psycopg.connect(checkpoint_dsn) as connection:
        connection.execute("""CREATE FUNCTION fail_checkpoint_head_publish() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'injected publish failure'; END; $$ LANGUAGE plpgsql""")
        connection.execute("""CREATE TRIGGER fail_checkpoint_head_publish BEFORE UPDATE
            ON task_projection_heads FOR EACH ROW
            EXECUTE FUNCTION fail_checkpoint_head_publish()""")
    with pytest.raises(psycopg.errors.RaiseException, match="injected"):
        _store(checkpoint_dsn).commit_projection_page(
            _page(scope, rows, 0, 2, cells=(ProjectionCell(_key(scope), 1, "1"),))
        )
    assert _counts(checkpoint_dsn) == (0, 0, 0, 0)


def test_concurrent_first_commit_has_one_cas_winner(checkpoint_dsn: str) -> None:
    scope, rows = _seed(checkpoint_dsn)
    page = _page(scope, rows, 0, 2)

    def attempt() -> str:
        try:
            _store(checkpoint_dsn).commit_projection_page(page)
            return "winner"
        except CheckpointConflict:
            return "lost-CAS"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == ["lost-CAS", "winner"]
    assert _counts(checkpoint_dsn) == (1, 2, 2, 0)


def test_commit_does_not_wait_for_task_session_or_source_locks(checkpoint_dsn: str) -> None:
    scope, rows = _seed(checkpoint_dsn)
    with psycopg.connect(checkpoint_dsn) as owner:
        owner.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,61))", (f"{NS}:{scope.task_id}",)
        )
        owner.execute("SELECT task_id FROM agent_tasks FOR UPDATE")
        owner.execute("SELECT session_id FROM session_streams FOR UPDATE")
        owner.execute("SELECT event_id FROM session_events FOR UPDATE")
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(
                _store(checkpoint_dsn).commit_projection_page, _page(scope, rows, 0, 1)
            ).result(timeout=3)
        assert result.through_sequence == 0


def test_readonly_transaction_never_hydrates_bodies_or_all_cells(
    checkpoint_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope, rows = _seed(checkpoint_dsn)
    store, key = _store(checkpoint_dsn), _key(scope)
    store.commit_projection_page(
        _page(scope, rows, 0, 2, cells=(ProjectionCell(key, 0, "1"), ProjectionCell(key, 1, None)))
    )
    original = store._database.connect_task_io

    def readonly() -> Any:
        connection = original()
        connection.execute("SET TRANSACTION READ ONLY")
        return connection

    monkeypatch.setattr(store._database, "connect_task_io", readonly)
    assert store.read_checkpoint_head(scope).through_sequence == 1
    assert store.read_event_projection_header(scope, 1) is not None
    assert store.read_segment_checkpoint_before(scope, key.segment_id, 2).task_sequence == 1
    assert store.read_cells_at(scope, 2, (key,))[0].value is None


@pytest.mark.parametrize("count", [1_000, 10_000, 100_000])
def test_latest_key_and_scalar_reads_use_bounded_indexes(
    checkpoint_dsn: str,
    count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope, rows = _seed(checkpoint_dsn, count)
    store, key = _store(checkpoint_dsn), _key(scope)
    store.commit_projection_page(_page(scope, rows, 0, 1, cells=(ProjectionCell(key, 0, "1"),)))
    with psycopg.connect(checkpoint_dsn) as connection:
        connection.execute("SET LOCAL statement_timeout='60s'")
        # ponytail: fixture-only raw history; <=256 headers/COPY rows per batch.
        # Production pages still validate every header. Analyze the FK parent
        # before loading children so cached FK plans never see a tiny parent.
        tables: tuple[tuple[str, str, Callable[[tuple[Any, ...]], tuple[Any, ...]]], ...] = (
            (
                "frames",
                "task_sequence,event_id,segment_id,segment_sequence,state_before_sequence,frame_count,projected,eligible",
                lambda row: (*row, row[0] - 1, 1, True, True),
            ),
            (
                "scalars",
                "segment_id,task_sequence,segment_sequence,started,turn_finished",
                lambda row: (row[2], row[0], row[3], True, False),
            ),
            (
                "cells",
                "segment_id,cell_kind,cell_key,task_sequence,value,byte_count",
                lambda row: (row[2], key.kind, key.key, row[0], "1", 286),
            ),
        )
        for table, columns, values in tables:
            for start in range(1, count, 256):
                records = connection.execute(
                    """SELECT task_sequence,event_id,session_id,sequence FROM session_events
                       WHERE deployment_namespace=%s AND task_id=%s
                         AND task_sequence>=%s AND task_sequence<%s
                       ORDER BY task_sequence LIMIT 256""",
                    (NS, scope.task_id, start, min(start + 256, count)),
                ).fetchall()
                with (
                    connection.cursor() as cursor,
                    cursor.copy(
                        sql.SQL("""COPY {} (deployment_namespace,task_id,anchor_key,
                        projector_version,{}) FROM STDIN""").format(
                            sql.Identifier(f"task_projection_{table}"), sql.SQL(columns)
                        )
                    ) as bulk,
                ):
                    for row in records:
                        bulk.write_row(
                            (NS, scope.task_id, "", scope.projector_version, *values(row))
                        )
            connection.execute(
                sql.SQL("ANALYZE {}").format(sql.Identifier(f"task_projection_{table}"))
            )
        connection.execute(
            """UPDATE task_projection_heads SET through_sequence=%s,last_event_id=(
                SELECT event_id FROM session_events WHERE deployment_namespace=%s
                AND task_id=%s AND task_sequence=%s),latest_eligible_sequence=%s
               WHERE deployment_namespace=%s AND task_id=%s""",
            (count - 1, NS, scope.task_id, count - 1, count - 1, NS, scope.task_id),
        )
    queries: list[tuple[str, Any]] = []

    class TracedConnection(psycopg.Connection[dict[str, Any]]):
        def execute(
            self,
            query: Any,
            params: Any = None,
            *,
            prepare: bool | None = None,
            binary: bool = False,
        ) -> psycopg.Cursor[dict[str, Any]]:
            if isinstance(query, str) and any(
                f"FROM task_projection_{table}" in query for table in ("cells", "scalars")
            ):
                queries.append((query, params))
            return super().execute(query, params, prepare=prepare, binary=binary)

    monkeypatch.setattr(
        store._database,
        "connect_task_io",
        lambda: TracedConnection.connect(checkpoint_dsn, row_factory=dict_row),
    )
    assert store.read_cells_at(scope, count, (key,))[0].task_sequence == count - 1
    assert (
        store.read_segment_checkpoint_before(scope, key.segment_id, count).task_sequence
        == count - 1
    )
    assert len(queries) == 3  # Actual metadata admission, exact value, strict-before scalar SQL.
    with psycopg.connect(checkpoint_dsn) as connection:
        for query, params in queries:
            plan_row = connection.execute(
                "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + query, params
            ).fetchone()
            assert plan_row is not None
            plan = plan_row[0][0]["Plan"]
            pending = [plan]
            indexed = False
            while pending:
                node = pending.pop()
                assert node["Actual Rows"] + node.get("Rows Removed by Filter", 0) <= 1, node
                indexed |= "Index" in node["Node Type"]
                pending.extend(node.get("Plans", []))
            assert indexed
