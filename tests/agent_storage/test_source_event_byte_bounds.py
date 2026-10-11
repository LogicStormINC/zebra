"""Source-owned byte admission and immutable assigned business bodies."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import CorrelationId, EventId, TaskId, new_session_id
from agent_core.ports.agent_tasks import TaskEvent
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore
from agent_storage.database import SQLiteDatabase
from agent_storage.task_event_page_limits import build_event_page
from agent_storage.task_event_positions import repair_task_event_index
from psycopg.rows import dict_row

from tests.agent_storage.test_postgres_task_positions_quality import NS, _ready, _source
from tests.agent_storage.test_postgres_task_positions_quality import positions_dsn as _pg_fixture
from tests.agent_storage.test_task_event_pages import _task
from tests.agent_storage.test_task_event_positions import _seed

positions_dsn = _pg_fixture

_IMMUTABLE_BUSINESS_SOURCE = (
    r"^(?:canonical Task Event business fields are|"
    r"(?:projection metadata|replay header) source is) immutable$"
)


@pytest.mark.parametrize(
    "column,value",
    [
        ("payload", '{"title":"changed"}'),
        ("actor", "user"),
        ("created_at", "2026-01-01T00:00:00+00:00"),
        ("causation_id", str(uuid4())),
        ("correlation_id", str(uuid4())),
        ("idempotency_key", "changed"),
        ("policy_version", "changed"),
        ("model_profile", "changed"),
        ("event_type", "session_title_updated"),
    ],
)
def test_assigned_business_fields_are_immutable(tmp_path: Path, column: str, value: str) -> None:
    database = tmp_path / "immutable.sqlite"
    _task(database, 1)
    with SQLiteDatabase(database).connect() as connection:
        before = tuple(connection.execute("SELECT * FROM session_events").fetchone())
        with pytest.raises(sqlite3.IntegrityError, match=_IMMUTABLE_BUSINESS_SOURCE):
            connection.execute(f"UPDATE session_events SET {column}=?", (value,))
        assert tuple(connection.execute("SELECT * FROM session_events").fetchone()) == before
        connection.execute("UPDATE session_events SET payload=payload,actor=actor")


def test_body_growth_between_admission_and_hydration_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_storage import task_event_pages

    database = tmp_path / "race.sqlite"
    store, task = _task(database, 1)
    original = task_event_pages.deserialize_event_row
    hydrated: list[int] = []

    def counted(row: sqlite3.Row) -> SessionEvent:
        hydrated.append(len(row["payload"].encode()))
        return original(row)

    monkeypatch.setattr(task_event_pages, "deserialize_event_row", counted)
    with SQLiteDatabase(database).connect() as reader:

        class ConcurrentWriter:
            def execute(self, statement: str, parameters: tuple[object, ...] = ()):
                if statement.lstrip().startswith("SELECT * FROM session_events"):
                    with SQLiteDatabase(database).connect() as writer:
                        with pytest.raises(
                            sqlite3.IntegrityError, match=_IMMUTABLE_BUSINESS_SOURCE
                        ):
                            writer.execute(
                                "UPDATE session_events SET payload=?",
                                (json.dumps({"title": "x" * 2_097_152}),),
                            )
                return reader.execute(statement, parameters)

        page = task_event_pages.read_task_event_page(
            ConcurrentWriter(),  # type: ignore[arg-type]
            task.task_id,
            -1,
            limit=1,
            max_bytes=1024,
            through=None,
        )
        assert reader.total_changes == 0
    assert len(page.events) == 1 and hydrated == [len('{"title": "Title 0"}')]
    assert store.read_event_page(task.task_id, -1).events == page.events


def test_noncanonical_numeric_payload_bound_covers_typed_serialization(tmp_path: Path) -> None:
    database = tmp_path / "numeric.sqlite"
    session = _seed(database)
    event = SessionEvent.create(
        session_id=session,
        sequence=1,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "probe",
            "tool_call_id": str(uuid4()),
            "status": "completed",
            "output": "",
            "metadata": {"values": [1e9] * 256},
        },
    )
    SQLiteEventStore(database).append(event)
    raw = json.dumps(event.payload, separators=(",", ":")).replace("1000000000.0", "1e9")
    with SQLiteDatabase(database).connect() as connection:
        connection.execute(
            "UPDATE session_events SET payload=? WHERE event_id=?", (raw, str(event.event_id))
        )
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(session)  # Explicit bounded source adoption fills v2.
    with SQLiteDatabase(database).connect() as connection:
        bound = connection.execute(
            "SELECT event_bytes_bound FROM session_events WHERE event_id=?", (str(event.event_id),)
        ).fetchone()[0]
    actual = build_event_page(
        (TaskEvent(session, 1, session, 1, event),),
        after=0,
        highwater=1,
        max_bytes=1_048_576,
    ).byte_count
    assert bound >= actual > len(raw.encode()) + 768
    assert store.read_event_page(task.task_id, 0, max_bytes=bound).byte_count == actual


def test_upgrade_invalidates_old_nonnull_bounds_without_body_scan_then_repairs_in_batches(
    tmp_path: Path,
) -> None:
    from agent_storage.task_event_positions import initialize_task_positions

    database = tmp_path / "upgrade.sqlite"
    store, task = _task(database, 5)
    with SQLiteDatabase(database).connect() as connection:
        # Reconstruct a v1 installed scalar, including pre-existing nonnull low bounds.
        for name in ("insert", "update", "guard"):
            connection.execute(f"DROP TRIGGER session_events_byte_bound_{name}")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(session_events)")}
        if "event_bytes_bound_v1" in columns:
            connection.execute("ALTER TABLE session_events DROP COLUMN event_bytes_bound_v1")
        connection.execute("UPDATE session_events SET event_bytes_bound=1")
        before = [tuple(row)[:14] for row in connection.execute("SELECT * FROM session_events")]
        touched: list[object] = []
        connection.create_function("length", 1, lambda value: touched.append(value) or len(value))
        initialize_task_positions(connection)
        assert touched == []
        assert [
            tuple(row)[:14] for row in connection.execute("SELECT * FROM session_events")
        ] == before
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM session_events WHERE event_bytes_bound IS NULL"
            ).fetchone()[0]
            == 5
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM session_events WHERE event_bytes_bound_v1=1"
            ).fetchone()[0]
            == 5
        )
    with pytest.raises(ValueError, match="explicit backfill"):
        store.read_event_page(task.task_id, -1)
    for remaining in (3, 1, 0):
        with SQLiteDatabase(database).connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            assert repair_task_event_index(connection, task.task_id, limit=2) == 0
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM session_events WHERE event_bytes_bound IS NULL"
                ).fetchone()[0]
                == remaining
            )
    assert len(store.read_event_page(task.task_id, -1).events) == 5
    with SQLiteDatabase(database).connect() as connection:
        bounds = list(connection.execute("SELECT event_bytes_bound FROM session_events"))
        initialize_task_positions(connection)
        assert list(connection.execute("SELECT event_bytes_bound FROM session_events")) == bounds
        # Explicit repair recomputes *nonnull* cells too, without rewriting business data.
        connection.execute("DROP TRIGGER session_events_byte_bound_guard")
        connection.execute("UPDATE session_events SET event_bytes_bound=1")
        repair_task_event_index(connection, task.task_id, limit=2)
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM session_events WHERE event_bytes_bound=1"
            ).fetchone()[0]
            == 3
        )


def test_escaped_metadata_and_extreme_fixed_envelope(tmp_path: Path) -> None:
    database = tmp_path / "envelope.sqlite"
    store, task = _task(database, 1)
    escaped = '\x00\x01\b\t\n\r\x1f"\\雪😀' * 200
    event = SessionEvent(
        event_id=EventId(uuid4()),
        session_id=task.active_segment_id,
        sequence=1,
        event_type=EventType.SESSION_TITLE_UPDATED,
        actor=EventActor.SYSTEM,
        payload={"title": "escaped", "numbers": [-1.7976931348623157e308, 5e-324, -0.0]},
        created_at=datetime(
            9999, 12, 31, 23, 59, 59, 999999, tzinfo=timezone(timedelta(hours=23, minutes=59))
        ),
        causation_id=EventId(uuid4()),
        correlation_id=CorrelationId(uuid4()),
        idempotency_key=escaped,
        policy_version=escaped,
        model_profile=escaped,
    )
    SQLiteEventStore(database).append(event)
    with SQLiteDatabase(database).connect() as connection:
        bound = connection.execute(
            "SELECT event_bytes_bound FROM session_events WHERE sequence=1"
        ).fetchone()[0]
    page = store.read_event_page(task.task_id, 0, limit=1, max_bytes=bound)
    assert page.byte_count <= bound


def test_assignment_cannot_change_business_fields_in_same_statement(tmp_path: Path) -> None:
    database = tmp_path / "adoption.sqlite"
    session = new_session_id()
    SQLiteEventStore(database).append(
        SessionEvent.create(
            session_id=session,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "before"},
            created_at=datetime.now(UTC),
        )
    )
    SQLiteAgentTaskStore(database)
    with SQLiteDatabase(database).connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="business.*immutable"):
            connection.execute(
                "UPDATE session_events SET task_id=?,task_sequence=0,payload=?",
                (str(session), '{"title":"changed during adoption"}'),
            )
        connection.execute("UPDATE session_events SET task_id=?,task_sequence=0", (str(session),))


def test_issued_migration_checksums_are_frozen() -> None:
    from agent_storage.postgres.task_event_bytes_migration import TASK_EVENT_BYTES_MIGRATION
    from agent_storage.postgres.task_event_positions_migration import TASK_EVENT_POSITIONS_MIGRATION

    assert TASK_EVENT_POSITIONS_MIGRATION.checksum == (
        "c5122793d027451af85713d12296f92dad07bd093194244308cdf84cd7260d21"
    )
    assert TASK_EVENT_BYTES_MIGRATION.checksum == (
        "5cbbe06c454976554454299c739d7008f329b92cb6e20bd5a54bcbf96b1d0298"
    )


@pytest.mark.parametrize(
    "token",
    ["1e9", "NaN", "Infinity", "1e999", "5e-324", "-1.7976931348623157e308", "9223372036854775808"],
)
def test_legacy_numeric_tokens_cover_maximum_typed_envelope(token: str) -> None:
    from agent_storage.task_event_bytes_schema import BYTE_BOUND

    session = new_session_id()
    maximum = 2**63 - 1
    raw = '{"values":[' + ",".join([token] * 256) + "]}"
    event = SessionEvent(
        event_id=EventId(uuid4()),
        session_id=session,
        sequence=maximum,
        event_type=EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED,
        actor=EventActor.HARNESS,
        payload=json.loads(raw),
        created_at=datetime(
            9999, 12, 31, 23, 59, 59, 999999, tzinfo=timezone(timedelta(hours=23, minutes=59))
        ),
        causation_id=EventId(uuid4()),
        correlation_id=CorrelationId(uuid4()),
    )
    actual = build_event_page(
        (TaskEvent(session, maximum, session, maximum, event),),
        after=maximum - 1,
        highwater=maximum,
        max_bytes=1_048_576,
    ).byte_count
    with sqlite3.connect(":memory:") as connection:
        bound = connection.execute(
            f"SELECT {BYTE_BOUND} FROM (SELECT ? AS payload,NULL AS idempotency_key,"
            "NULL AS policy_version,NULL AS model_profile)",
            (raw,),
        ).fetchone()[0]
    assert bound >= actual


@pytest.fixture
def old_source_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_storage.postgres import migration_runner

    # The existing quality fixture creates/migrates/drops its own UUID database.
    # Exercise the *upgrade* from issued v63 even after main publishes v65/v66.
    monkeypatch.setattr(
        migration_runner,
        "MIGRATIONS",
        tuple(m for m in migration_runner.MIGRATIONS if m.version <= 64),
    )


@pytest.fixture
def source_pg_dsn(old_source_catalog: None, positions_dsn: str) -> str:
    return positions_dsn


def _upgrade_source_bounds(dsn: str) -> None:
    from agent_storage.postgres.task_event_source_bounds_migration import (
        TASK_EVENT_SOURCE_BOUNDS_MIGRATION,
    )

    with psycopg.connect(dsn) as connection:
        for statement in TASK_EVENT_SOURCE_BOUNDS_MIGRATION.statements:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO zebra_schema_migrations(version,name,checksum) VALUES (%s,%s,%s)",
            (
                65,
                TASK_EVENT_SOURCE_BOUNDS_MIGRATION.name,
                TASK_EVENT_SOURCE_BOUNDS_MIGRATION.checksum,
            ),
        )


@pytest.mark.parametrize(
    "column,value",
    [
        ("payload", '{"title":"changed"}'),
        ("actor", "user"),
        ("created_at", "2026-01-01T00:00:00+00:00"),
        ("causation_id", str(uuid4())),
        ("correlation_id", str(uuid4())),
        ("idempotency_key", "changed"),
        ("policy_version", "changed"),
        ("model_profile", "changed"),
        ("event_type", "session_created"),
    ],
)
def test_postgres_assigned_business_fields_are_immutable(
    source_pg_dsn: str, column: str, value: str
) -> None:
    root = _ready(source_pg_dsn, 1)
    _upgrade_source_bounds(source_pg_dsn)
    with psycopg.connect(source_pg_dsn) as connection:
        with connection.transaction():
            with pytest.raises(
                psycopg.errors.ObjectNotInPrerequisiteState, match="business.*immutable"
            ):
                with connection.transaction():
                    connection.execute(
                        f"UPDATE session_events SET {column}=%s WHERE session_id=%s", (value, root)
                    )
        connection.execute("UPDATE session_events SET payload=payload,actor=actor")
        # Retargeted UPDATE OF must compute the *new* scalar, not the retired column.
        connection.execute("UPDATE session_events SET event_bytes_bound=1")
        assert (
            connection.execute("SELECT event_bytes_bound FROM session_events").fetchone()[0] > 768
        )


def test_postgres_upgrade_and_nonnull_repair_are_bounded(source_pg_dsn: str) -> None:
    from agent_storage.postgres.task_event_pages import read_task_event_page
    from agent_storage.postgres.task_event_positions import repair_task_event_index as repair

    root = _ready(source_pg_dsn, 5)
    with psycopg.connect(source_pg_dsn) as connection:
        connection.execute("ALTER TABLE session_events DISABLE TRIGGER session_events_byte_bound")
        connection.execute("UPDATE session_events SET event_bytes_bound=1")
        connection.execute("ALTER TABLE session_events ENABLE TRIGGER session_events_byte_bound")
        before = connection.execute(
            "SELECT xmin::text,ctid::text,event_id,payload FROM session_events ORDER BY sequence"
        ).fetchall()
    _upgrade_source_bounds(source_pg_dsn)
    with psycopg.connect(source_pg_dsn, row_factory=dict_row) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) AS n FROM session_events WHERE event_bytes_bound IS NULL "
                "AND event_bytes_bound_v1=1"
            ).fetchone()["n"]
            == 5
        )
        after = connection.execute(
            "SELECT xmin::text,ctid::text,event_id,payload FROM session_events ORDER BY sequence"
        ).fetchall()
        assert [tuple(row.values()) for row in after] == before  # No upgrade-time row/body rewrite.
        with pytest.raises(ValueError, match="explicit backfill"):
            read_task_event_page(
                connection, NS, TaskId(root), -1, limit=5, max_bytes=10_000, through=None
            )
    for remaining in (3, 1, 0):
        with psycopg.connect(source_pg_dsn, row_factory=dict_row) as connection:
            assert repair(connection, NS, TaskId(root), limit=2) == 0
            assert (
                connection.execute(
                    "SELECT COUNT(*) AS n FROM session_events WHERE event_bytes_bound IS NULL"
                ).fetchone()["n"]
                == remaining
            )
    with psycopg.connect(source_pg_dsn, row_factory=dict_row) as connection:
        connection.execute("ALTER TABLE session_events DISABLE TRIGGER session_events_byte_bound")
        connection.execute("UPDATE session_events SET event_bytes_bound=1")
        connection.execute("ALTER TABLE session_events ENABLE TRIGGER session_events_byte_bound")
        assert repair(connection, NS, TaskId(root), limit=2) == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) AS n FROM session_events WHERE event_bytes_bound=1"
            ).fetchone()["n"]
            == 3
        )


def test_postgres_numeric_escaped_bound_and_same_value_numeric_update(
    source_pg_dsn: str,
) -> None:
    from agent_storage.postgres.task_event_pages import read_task_event_page
    from agent_storage.postgres.task_event_positions import backfill_task_event_positions

    _upgrade_source_bounds(source_pg_dsn)
    escaped = '\x01\b\t\n\r\x1f"\\雪😀' * 100  # PostgreSQL TEXT cannot store NUL.
    raw = (
        '{"title":"numbers","nested":[{"values":['
        + ",".join(["1e9", "-1.7976931348623157e308", "5e-324", "-0.0"] * 64)
        + "]}]}"
    )
    with psycopg.connect(source_pg_dsn) as connection:
        root = _source(connection, 1)
        connection.execute(
            "UPDATE session_events SET payload=%s,policy_version=%s,model_profile=%s,"
            "idempotency_key=%s,causation_id=%s,correlation_id=%s WHERE session_id=%s",
            (raw, escaped, escaped, escaped, uuid4(), uuid4(), root),
        )
        # Native initial coordinate adoption is still legal; body+adoption is not.
        with pytest.raises(
            psycopg.errors.ObjectNotInPrerequisiteState, match="business.*immutable"
        ):
            with connection.transaction():
                connection.execute(
                    "UPDATE session_events SET task_id=%s,task_sequence=0,actor='tool'",
                    (root,),
                )
    from tests.agent_storage.test_postgres_task_positions_quality import _member

    with psycopg.connect(source_pg_dsn, row_factory=dict_row) as connection:
        _member(connection, root)
        assert backfill_task_event_positions(connection, NS, TaskId(root))
        bound = connection.execute("SELECT event_bytes_bound FROM session_events").fetchone()[
            "event_bytes_bound"
        ]
        page = read_task_event_page(
            connection, NS, TaskId(root), -1, limit=1, max_bytes=bound, through=None
        )
        assert page.byte_count <= bound
        # JSONB equality considers 1 and 1.0 equal, but typed body bytes can change.
        with pytest.raises(
            psycopg.errors.ObjectNotInPrerequisiteState, match="business.*immutable"
        ):
            with connection.transaction():
                connection.execute(
                    "UPDATE session_events SET payload=jsonb_set(payload,'{nested,0,values,0}',"
                    "'1000000000.0'::jsonb)"
                )


def test_postgres_growth_between_admission_and_hydration_is_rejected(source_pg_dsn: str) -> None:
    from agent_storage.postgres.task_event_pages import read_task_event_page
    from agent_storage.postgres.task_event_positions import repair_task_event_index as repair

    root = _ready(source_pg_dsn, 1)
    _upgrade_source_bounds(source_pg_dsn)
    with psycopg.connect(source_pg_dsn, row_factory=dict_row) as connection:
        repair(connection, NS, TaskId(root))
    with psycopg.connect(source_pg_dsn, row_factory=dict_row) as reader:

        class ConcurrentWriter:
            def execute(self, statement: str, parameters: tuple[Any, ...] = ()):
                if "AS segment_id" in statement:
                    with psycopg.connect(source_pg_dsn) as writer:
                        with pytest.raises(
                            psycopg.errors.ObjectNotInPrerequisiteState, match="business.*immutable"
                        ):
                            with writer.transaction():
                                writer.execute(
                                    "UPDATE session_events SET payload=%s WHERE session_id=%s",
                                    (json.dumps({"title": "x" * 2_097_152}), root),
                                )
                return reader.execute(statement, parameters)

        page = read_task_event_page(
            ConcurrentWriter(), NS, TaskId(root), -1, limit=1, max_bytes=1024, through=None
        )
        assert len(page.events) == 1 and page.events[0].event.payload == {"title": "test"}
