"""Real isolated PG source metadata, snapshot, lock-order and index proofs."""

import json
import os
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from queue import Queue
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_storage.postgres import apply_postgres_migrations
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.projection_source_metadata import (
    PostgresProjectionSourceMetadataMixin,
    backfill_projection_source_metadata,
    write_projection_source_metadata,
)
from agent_storage.postgres.projection_source_metadata_migration import (
    TASK_PROJECTION_SOURCE_METADATA_MIGRATION,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

NS = "source-projection-quality"
Connection = psycopg.Connection[dict[str, Any]]


@pytest.fixture
def metadata_dsn() -> Generator[str]:
    configured = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not configured:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN with CREATEDB privilege")
    admin_dsn = make_conninfo(configured, dbname="postgres")
    name = f"zebra_projection_metadata_{uuid4().hex}"
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        dsn = make_conninfo(configured, dbname=name)
        apply_postgres_migrations(dsn)
        with psycopg.connect(dsn) as connection:
            migration = TASK_PROJECTION_SOURCE_METADATA_MIGRATION
            applied = connection.execute(
                "SELECT name,checksum FROM zebra_schema_migrations WHERE version=67"
            ).fetchone()
            if applied is None:  # Main owns catalog registration.
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


class Store(PostgresProjectionSourceMetadataMixin):
    def __init__(self, dsn: str, namespace: str = NS) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=namespace)


def seed(connection: Connection, count: int = 0) -> tuple[TaskId, SessionId, SessionId]:
    task, b = TaskId(uuid4()), SessionId(uuid4())
    a = SessionId(task)
    for segment in (a, b):
        connection.execute("INSERT INTO session_streams VALUES (%s,%s,0)", (NS, segment))
        connection.execute(
            "INSERT INTO session_projections "
            "(deployment_namespace,session_id,title,status,created_at,updated_at,current_sequence) "
            "VALUES (%s,%s,'projection','created',now(),now(),0)",
            (NS, segment),
        )
    # Coordinates may be restored before canonical membership during import.
    created = datetime.now(UTC)
    for start in range(0, count, 256):
        stop = min(count, start + 256)
        with connection.cursor().copy(
            "COPY session_events(deployment_namespace,event_id,session_id,sequence,"
            "event_type,payload,actor,created_at) FROM STDIN"
        ) as bulk:
            for n in range(start, stop):
                bulk.write_row(
                    (
                        NS,
                        uuid4(),
                        a,
                        n,
                        "session_title_updated",
                        '{"title":"seed"}',
                        "system",
                        created,
                    )
                )
        connection.execute(
            "UPDATE session_events SET task_id=%s,task_sequence=sequence "
            "WHERE deployment_namespace=%s AND session_id=%s AND sequence>=%s AND sequence<%s",
            (task, NS, a, start, stop),
        )
        connection.commit()  # Bound deferred source work to <=256 rows.
    connection.execute(
        "INSERT INTO agent_tasks(deployment_namespace,task_id,root_session_id,active_segment_id,"
        "created_at,updated_at,next_event_sequence,event_position_state) "
        "VALUES (%s,%s,%s,%s,now(),now(),%s,'ready')",
        (NS, task, a, a, count),
    )
    for n, segment in enumerate((a, b)):
        connection.execute(
            "INSERT INTO execution_segments(deployment_namespace,session_id,task_id,"
            "predecessor_id,segment_index,"
            "visibility,event_position_source_cursor,event_position_source_ready) "
            "VALUES (%s,%s,%s,%s,%s,'internal',%s,true)",
            (NS, segment, task, None if n == 0 else a, n, count - 1 if segment == a else -1),
        )
    connection.commit()
    return task, a, b


def append(
    connection: Connection,
    segment: SessionId,
    sequence: int,
    *,
    kind: str = "session_title_updated",
    handoff: UUID | None = None,
    peer: SessionId | None = None,
) -> EventId:
    event = EventId(uuid4())
    payload = (
        {"title": "metadata"}
        if handoff is None
        else {
            "handoff_id": str(handoff),
            "target_session_id"
            if kind == "session_handoff_committed"
            else "parent_session_id": str(peer),
        }
    )
    connection.execute(
        "INSERT INTO session_events(deployment_namespace,event_id,session_id,sequence,event_type,"
        "payload,actor,created_at) VALUES (%s,%s,%s,%s,%s,%s,'system',now())",
        (NS, event, segment, sequence, kind, json.dumps(payload)),
    )
    connection.commit()  # Real deferred allocator, no manual position allocation.
    return event


def test_native_allocator_late_segment_and_snapshot(metadata_dsn: str) -> None:
    with psycopg.connect(metadata_dsn, row_factory=dict_row) as connection:
        task, a, b = seed(connection)
        for segment, n in ((a, 0), (a, 1), (b, 0), (b, 1), (a, 2), (a, 3)):
            append(connection, segment, n)
    block = Store(metadata_dsn).read_projection_block(task, 5, through_sequence=5)
    assert (
        block.segment_id,
        block.first_task_sequence,
        block.last_task_sequence,
        block.first_segment_sequence,
        block.last_segment_sequence,
        block.previous_block_start,
    ) == (a, 4, 5, 2, 3, 0)
    assert (
        Store(metadata_dsn).read_projection_block(task, 4, through_sequence=4).last_task_sequence
        == 4
    )


def test_commit_orphan_and_conflicting_latest_not_filtered(metadata_dsn: str) -> None:
    with psycopg.connect(metadata_dsn, row_factory=dict_row) as connection:
        task, a, b = seed(connection)
        orphan, handoff = uuid4(), uuid4()
        append(connection, b, 0, kind="session_handoff_received", handoff=orphan, peer=a)
        append(connection, a, 0, kind="session_handoff_committed", handoff=handoff, peer=b)
        append(
            connection,
            a,
            1,
            kind="session_handoff_committed",
            handoff=handoff,
            peer=SessionId(uuid4()),
        )
        append(connection, b, 1, kind="session_handoff_received", handoff=handoff, peer=a)
    store = Store(metadata_dsn)
    assert store.read_latest_handoff_commit(task, a, orphan, 1, through_sequence=3) is None
    assert store.read_latest_handoff_commit(task, a, handoff, 1, through_sequence=3) is None
    previous = store.read_latest_handoff_commit(task, a, handoff, 2, through_sequence=3)
    latest = store.read_latest_handoff_commit(task, a, handoff, 3, through_sequence=3)
    assert previous is not None and previous.peer_segment_id == b
    assert latest is not None and latest.source.task_sequence == 2 and latest.peer_segment_id != b
    assert len(store.read_handoff_receives(task, b, through_sequence=3)) == 2
    assert store.read_handoff_receives(task, a, through_sequence=3) == ()


def test_receive_ambiguity_is_conflict_not_notready(metadata_dsn: str) -> None:
    with psycopg.connect(metadata_dsn, row_factory=dict_row) as connection:
        task, a, b = seed(connection)
        handoff = uuid4()
        append(connection, a, 0, kind="session_handoff_committed", handoff=handoff, peer=b)
        append(connection, b, 0, kind="session_handoff_received", handoff=handoff, peer=a)
        append(connection, b, 1, kind="session_handoff_received", handoff=handoff, peer=a)
    assert len(Store(metadata_dsn).read_handoff_receives(task, b, through_sequence=1)) == 1
    with pytest.raises(CheckpointConflict, match="ambiguous"):
        Store(metadata_dsn).read_handoff_receives(task, b, through_sequence=2)


def test_import_membership_and_bounded_frozen_repair(metadata_dsn: str) -> None:
    with psycopg.connect(metadata_dsn, row_factory=dict_row) as connection:
        task, a, _ = seed(connection, 600)
        with pytest.raises(CheckpointNotReady, match="explicit backfill"):
            Store(metadata_dsn).read_projection_block(task, 0, through_sequence=599)
        assert not backfill_projection_source_metadata(connection, NS, task)
        connection.commit()
    with psycopg.connect(metadata_dsn, row_factory=dict_row) as connection:
        assert not backfill_projection_source_metadata(connection, NS, task)
        connection.commit()
        append(connection, a, 600)  # Not part of the already frozen repair cycle.
        assert backfill_projection_source_metadata(connection, NS, task)
        connection.commit()
        head = connection.execute(
            "SELECT repair_cursor,repair_highwater FROM task_projection_source_heads"
        ).fetchone()
        assert head == {"repair_cursor": -1, "repair_highwater": -1}
    assert (
        Store(metadata_dsn)
        .read_projection_block(task, 599, through_sequence=599)
        .last_task_sequence
        == 599
    )
    with pytest.raises(CheckpointNotReady):
        Store(metadata_dsn).read_projection_block(task, 600, through_sequence=600)


def test_block_hole_repair_conflict_and_namespace(metadata_dsn: str) -> None:
    with psycopg.connect(metadata_dsn, row_factory=dict_row) as connection:
        task, a, _ = seed(connection)
        event = append(connection, a, 0)
        append(connection, a, 1)
        connection.execute("DELETE FROM task_projection_blocks")
        connection.commit()
        with pytest.raises(CheckpointConflict):
            Store(metadata_dsn).read_projection_block(task, 0, through_sequence=1)
        write_projection_source_metadata(connection, NS, event)
        connection.commit()
        assert (
            Store(metadata_dsn)
            .read_projection_block(task, 0, through_sequence=1)
            .last_task_sequence
            == 1
        )
        with pytest.raises(ValueError, match="namespace"):
            Store(metadata_dsn, "foreign").read_projection_block(task, 0, through_sequence=1)
        connection.execute(
            "UPDATE task_projection_blocks SET last_task_sequence=0,last_segment_sequence=0"
        )
        connection.commit()
        with pytest.raises(CheckpointConflict, match="range conflicts"):
            Store(metadata_dsn).read_projection_block(task, 0, through_sequence=1)
        with pytest.raises(CheckpointConflict, match="conflicts with source"):
            write_projection_source_metadata(connection, NS, event)


@pytest.mark.parametrize(
    "field,value",
    [
        ("projection_handoff_id", "NULL"),
        ("projection_block_start", "1"),
        ("payload", "'{}'::jsonb"),
    ],
)
def test_source_metadata_immutable(metadata_dsn: str, field: str, value: str) -> None:
    with psycopg.connect(metadata_dsn, row_factory=dict_row) as connection:
        _, a, b = seed(connection)
        event = append(connection, a, 0, kind="session_handoff_committed", handoff=uuid4(), peer=b)
        with pytest.raises(
            psycopg.errors.ObjectNotInPrerequisiteState, match="immutable|conflicts"
        ):
            connection.execute(
                f"UPDATE session_events SET {field}={value} WHERE event_id=%s", (event,)
            )


def test_repair_source_lock_precedes_head_without_task_or_segment_lock(metadata_dsn: str) -> None:
    with psycopg.connect(metadata_dsn, row_factory=dict_row) as connection:
        task, a, _ = seed(connection)
        event = append(connection, a, 0)
    with psycopg.connect(metadata_dsn, row_factory=dict_row) as holder:
        holder.execute("SELECT event_id FROM session_events WHERE event_id=%s FOR UPDATE", (event,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            worker_ids: Queue[int] = Queue()

            def repair() -> bool:
                with psycopg.connect(metadata_dsn, row_factory=dict_row) as worker:
                    worker.execute("SET lock_timeout='3s'")
                    worker_ids.put(worker.info.backend_pid)
                    return backfill_projection_source_metadata(worker, NS, task)

            future = pool.submit(repair)
            worker_id = worker_ids.get(timeout=2)
            deadline = time.monotonic() + 2
            while True:
                blocked = holder.execute("SELECT pg_blocking_pids(%s)", (worker_id,)).fetchone()
                assert blocked is not None
                if holder.info.backend_pid in blocked["pg_blocking_pids"]:
                    break
                assert time.monotonic() < deadline, "repair never reached the source lock"
                time.sleep(0.01)
            # NOWAIT succeeds while the repair is blocked on source, so no head-first inversion.
            holder.execute(
                "SELECT task_id FROM task_projection_source_heads "
                "WHERE task_id=%s FOR UPDATE NOWAIT",
                (task,),
            )
            holder.execute(
                "SELECT task_id FROM agent_tasks WHERE task_id=%s FOR UPDATE NOWAIT", (task,)
            )
            holder.execute(
                "SELECT session_id FROM execution_segments WHERE session_id=%s FOR UPDATE NOWAIT",
                (a,),
            )
            write_projection_source_metadata(holder, NS, event)
            holder.commit()
            assert future.result(timeout=5)


@pytest.mark.parametrize("count", [1000, 10000, 100000])
def test_actual_read_queries_are_metadata_only_index_seeks(metadata_dsn: str, count: int) -> None:
    with psycopg.connect(metadata_dsn, row_factory=dict_row) as connection:
        task, a, b = seed(connection, count)
        # Give the block table realistic selectivity without disabling seqscan.
        # These disjoint fixture rows cannot be read without a canonical Task.
        for start in range(0, 1024, 256):
            with connection.cursor().copy("COPY task_projection_blocks FROM STDIN") as bulk:
                for _ in range(start, start + 256):
                    bulk.write_row((NS, uuid4(), uuid4(), 0, 0, 0, 0, None))
        # ponytail: fixture seeds valid derived metadata in <=256-row batches;
        # this measures cold read plans, not 100k-event adoption throughput.
        connection.execute(
            "INSERT INTO task_projection_blocks VALUES (%s,%s,%s,0,%s,0,%s,NULL)",
            (NS, task, a, count - 1, count - 1),
        )
        for start in range(0, count, 256):
            connection.execute(
                "UPDATE session_events SET projection_block_start=0 "
                "WHERE deployment_namespace=%s AND task_id=%s "
                "AND task_sequence>=%s AND task_sequence<%s",
                (NS, task, start, min(start + 256, count)),
            )
            connection.commit()
        connection.execute(
            "INSERT INTO task_projection_source_heads"
            "(deployment_namespace,task_id,through_sequence) VALUES (%s,%s,%s)",
            (NS, task, count - 1),
        )
        connection.commit()
        handoff = uuid4()
        append(connection, a, count, kind="session_handoff_committed", handoff=handoff, peer=b)
        append(connection, b, 0, kind="session_handoff_received", handoff=handoff, peer=a)
        connection.execute("ANALYZE session_events")
        connection.execute("ANALYZE task_projection_blocks")
    captured: list[tuple[str, Any]] = []

    class TracedConnection(psycopg.Connection[dict[str, Any]]):
        def execute(self, query: Any, params: Any = None, **kwargs: Any) -> Any:
            if isinstance(query, str):
                captured.append((query, params))
                assert "payload" not in query.lower()
            return super().execute(query, params, **kwargs)

    class TracedDatabase(PostgresDatabase):
        def connect_task_io(self, **kwargs: Any) -> Connection:
            return TracedConnection.connect(metadata_dsn, row_factory=dict_row)

    store = Store(metadata_dsn)
    store._database = TracedDatabase(metadata_dsn, deployment_namespace=NS)
    assert (
        store.read_projection_block(task, count - 1, through_sequence=count + 1).last_task_sequence
        == count
    )
    assert len(store.read_handoff_receives(task, b, through_sequence=count + 1)) == 1
    latest = store.read_latest_handoff_commit(
        task, a, handoff, count + 1, through_sequence=count + 1
    )
    assert latest is not None and latest.source.task_sequence == count
    indexes: set[str] = set()

    def check(node: dict[str, Any]) -> None:
        assert node["Node Type"] not in {"Seq Scan", "Sort"}, json.dumps(node)
        assert node["Actual Rows"] + node.get("Rows Removed by Filter", 0) <= 2, json.dumps(node)
        if "Index Name" in node:
            indexes.add(node["Index Name"])
        for child in node.get("Plans", []):
            check(child)

    with psycopg.connect(metadata_dsn) as proof:
        for query, params in captured:
            if query.startswith("SELECT"):
                result = proof.execute("EXPLAIN (ANALYZE,FORMAT JSON) " + query, params).fetchone()
                assert result is not None
                check(result[0][0]["Plan"])
    assert "session_events_projection_receive" in indexes
    assert "session_events_projection_commit" in indexes


def test_multi_select_read_has_repeatable_read_snapshot(metadata_dsn: str) -> None:
    with psycopg.connect(metadata_dsn, row_factory=dict_row) as connection:
        task, a, _ = seed(connection)
        append(connection, a, 0)
    mutated = False

    class SnapshotConnection(psycopg.Connection[dict[str, Any]]):
        def execute(self, query: Any, params: Any = None, **kwargs: Any) -> Any:
            nonlocal mutated
            cursor = super().execute(query, params, **kwargs)
            if (
                isinstance(query, str)
                and query.startswith("SELECT next_event_sequence")
                and not mutated
            ):
                mutated = True
                with psycopg.connect(metadata_dsn) as writer:
                    writer.execute("DELETE FROM task_projection_blocks")
            return cursor

    class SnapshotDatabase(PostgresDatabase):
        def connect_task_io(self, **kwargs: Any) -> Connection:
            return SnapshotConnection.connect(metadata_dsn, row_factory=dict_row)

    store = Store(metadata_dsn)
    store._database = SnapshotDatabase(metadata_dsn, deployment_namespace=NS)
    assert store.read_projection_block(task, 0, through_sequence=0).segment_id == a
    assert mutated
    with pytest.raises(CheckpointConflict):
        Store(metadata_dsn).read_projection_block(task, 0, through_sequence=0)


def test_whole_block_requires_source_cursor_coverage(metadata_dsn: str) -> None:
    with psycopg.connect(metadata_dsn, row_factory=dict_row) as connection:
        task, a, _ = seed(connection)
        append(connection, a, 0)
        append(connection, a, 1)
        connection.execute(
            "UPDATE execution_segments SET event_position_source_cursor=0 "
            "WHERE deployment_namespace=%s AND session_id=%s",
            (NS, a),
        )
    with pytest.raises(CheckpointConflict, match="source coverage"):
        Store(metadata_dsn).read_projection_block(task, 0, through_sequence=1)
    assert (
        Store(metadata_dsn).read_projection_block(task, 0, through_sequence=0).last_segment_sequence
        == 0
    )
