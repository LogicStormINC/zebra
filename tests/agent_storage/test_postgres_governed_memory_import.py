import os
import sqlite3
from collections.abc import Generator
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.domain.governed_memories import (
    GovernedMemoryManagementContext,
    GovernedMemoryTombstone,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_storage import PostgresGovernedMemoryStore, apply_postgres_migrations
from agent_storage.postgres.governed_memory_import import (
    GovernedMemoryImportError,
    import_sqlite_governed_memories,
    legacy_import_creation_key_v1,
)
from agent_storage.postgres.governed_memory_import_support import (
    _postgres_values,
    _read_source,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
CURSOR_SIGNING_KEY = b"memory-import-test-signing-key-32-bytes"


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def isolated_dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"test_memory_import_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(dsn)
    yield dsn
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_import_creation_key_v1_is_stable_and_authority_canonical() -> None:
    record = _record(1)

    assert legacy_import_creation_key_v1(record) == canonical_governed_memory_creation_key(record)
    assert legacy_import_creation_key_v1(record) == (
        "61955d0020f59f0093c3082799cb76168740b91fd29a03aa5794e8429ae8c0f9"
    )


def test_read_source_uses_complete_keyset_and_preserves_deleted_as_tombstone_input(
    tmp_path: Path,
) -> None:
    source = tmp_path / "memory.sqlite3"
    _create_source(source, (_record(2, status=MemoryStatus.DELETED), _record(1)))

    prepared, source_count, issues = _read_source(source, page_size=1)

    assert source_count == 2
    assert not issues
    assert [str(item.record.memory_id) for item in prepared] == sorted(
        str(item.record.memory_id) for item in prepared
    )
    deleted = next(item for item in prepared if item.record.status is MemoryStatus.DELETED)
    values = _postgres_values("cloud-a", deleted)
    assert values[4] is None
    assert values[6] == MemoryStatus.DELETED.value


def test_source_preflight_is_complete_and_content_free_before_any_pg_connection(
    tmp_path: Path,
) -> None:
    source = tmp_path / "memory.sqlite3"
    valid = _record(1)
    invalid = _record(2).model_dump(mode="python")
    invalid["text"] = " migration secret "
    invalid["confidence"] = 2.0
    _create_source(source, (valid,), raw_rows=(invalid,))

    with pytest.raises(GovernedMemoryImportError) as caught:
        import_sqlite_governed_memories(
            source,
            "this DSN must never be reached",
            deployment_namespace="cloud-a",
            page_size=1,
        )

    report = caught.value.report
    assert report.source_count == 2
    assert report.imported_count == 0
    assert report.quarantine
    assert "migration secret" not in str(asdict(report))


def test_missing_source_is_not_created_and_returns_content_free_quarantine(
    tmp_path: Path,
) -> None:
    source = tmp_path / "missing.sqlite3"

    with pytest.raises(GovernedMemoryImportError) as caught:
        import_sqlite_governed_memories(
            source,
            "this DSN must never be reached",
            deployment_namespace="cloud-a",
        )

    assert not source.exists()
    assert caught.value.report.quarantine[0].code.startswith("sqlite_")


def test_duplicate_legacy_content_is_quarantined_before_pg(tmp_path: Path) -> None:
    source = tmp_path / "memory.sqlite3"
    first = _record(1)
    duplicate = first.model_copy(update={"memory_id": _memory_id(2)})
    _create_source(source, (first, duplicate))

    with pytest.raises(GovernedMemoryImportError) as caught:
        import_sqlite_governed_memories(
            source,
            "this DSN must never be reached",
            deployment_namespace="cloud-a",
        )

    assert {item.code for item in caught.value.report.quarantine} == {
        "duplicate_source_creation_key"
    }


def test_real_pg_import_replay_and_content_free_tombstone(
    tmp_path: Path,
    isolated_dsn: str,
) -> None:
    source = tmp_path / "memory.sqlite3"
    candidate = _record(1)
    deleted = _record(2, status=MemoryStatus.DELETED)
    _create_source(source, (candidate, deleted))

    first = import_sqlite_governed_memories(
        source,
        isolated_dsn,
        deployment_namespace="cloud-a",
        page_size=1,
    )
    replay = import_sqlite_governed_memories(
        source,
        isolated_dsn,
        deployment_namespace="cloud-a",
        page_size=1,
    )
    store = PostgresGovernedMemoryStore(
        isolated_dsn,
        deployment_namespace="cloud-a",
        cursor_signing_key=CURSOR_SIGNING_KEY,
    )

    assert first.source_count == first.imported_count == 2
    assert first.replayed_count == 0
    assert first.source_groups == first.target_groups
    assert first.fts_rebuilt is True
    assert replay.imported_count == 0
    assert replay.replayed_count == 2
    assert store.get(candidate.memory_id) == candidate
    assert store.get(deleted.memory_id) is None
    authority = store.get_authority(deleted.memory_id, management=_management())
    assert isinstance(authority, GovernedMemoryTombstone)
    with psycopg.connect(isolated_dsn) as connection:
        stored = connection.execute(
            """SELECT text, status FROM governed_memory_records
            WHERE deployment_namespace = 'cloud-a' AND memory_id = %s""",
            (deleted.memory_id,),
        ).fetchone()
    assert stored == (None, MemoryStatus.DELETED.value)


def test_real_pg_changed_same_id_fails_closed_without_partial_writes(
    tmp_path: Path,
    isolated_dsn: str,
) -> None:
    source = tmp_path / "memory.sqlite3"
    original = _record(1)
    second = _record(2)
    _create_source(source, (original, second))
    import_sqlite_governed_memories(
        source,
        isolated_dsn,
        deployment_namespace="cloud-a",
    )
    with sqlite3.connect(source) as connection:
        connection.execute(
            "UPDATE memory_records SET text = ? WHERE memory_id = ?",
            ("Changed after import.", str(original.memory_id)),
        )

    with pytest.raises(GovernedMemoryImportError) as caught:
        import_sqlite_governed_memories(
            source,
            isolated_dsn,
            deployment_namespace="cloud-a",
        )

    assert {item.code for item in caught.value.report.quarantine} == {"existing_authority_conflict"}
    store = PostgresGovernedMemoryStore(
        isolated_dsn,
        deployment_namespace="cloud-a",
        cursor_signing_key=CURSOR_SIGNING_KEY,
    )
    assert store.get(original.memory_id) == original
    with psycopg.connect(isolated_dsn) as connection:
        count = connection.execute(
            "SELECT count(*) FROM governed_memory_records WHERE deployment_namespace = 'cloud-a'"
        ).fetchone()
    assert count == (2,)


def test_real_pg_missing_source_session_and_events_preflight_zero_write(
    tmp_path: Path,
    isolated_dsn: str,
) -> None:
    source = tmp_path / "memory.sqlite3"
    record = _record(1).model_copy(
        update={
            "source_session_id": SessionId(UUID(int=99)),
            "source_event_start": 1,
            "source_event_end": 2,
        }
    )
    _create_source(source, (record,))

    with pytest.raises(GovernedMemoryImportError) as caught:
        import_sqlite_governed_memories(
            source,
            isolated_dsn,
            deployment_namespace="cloud-a",
        )

    assert {item.code for item in caught.value.report.quarantine} == {
        "missing_source_session",
        "missing_source_event",
    }
    with psycopg.connect(isolated_dsn) as connection:
        count = connection.execute("SELECT count(*) FROM governed_memory_records").fetchone()
    assert count == (0,)


def _create_source(
    path: Path,
    records: tuple[MemoryRecord, ...],
    *,
    raw_rows: tuple[dict[str, object], ...] = (),
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE memory_records (
                memory_id TEXT PRIMARY KEY, memory_type TEXT NOT NULL,
                text TEXT NOT NULL, confidence REAL NOT NULL, status TEXT NOT NULL,
                visibility TEXT NOT NULL, tenant_id TEXT, user_id TEXT, repo_id TEXT,
                source_session_id TEXT, source_event_start INTEGER,
                source_event_end INTEGER, source_commit_sha TEXT, superseded_by TEXT,
                expires_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
            """
        )
        for record in records:
            _insert(connection, record.model_dump(mode="python"))
        for row in raw_rows:
            _insert(connection, row)


def _insert(connection: sqlite3.Connection, row: dict[str, object]) -> None:
    connection.execute(
        """INSERT INTO memory_records VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(row["memory_id"]),
            _value(row["memory_type"]),
            row["text"],
            row["confidence"],
            _value(row["status"]),
            _value(row["visibility"]),
            row["tenant_id"],
            row["user_id"],
            row["repo_id"],
            None if row["source_session_id"] is None else str(row["source_session_id"]),
            row["source_event_start"],
            row["source_event_end"],
            row["source_commit_sha"],
            None if row["superseded_by"] is None else str(row["superseded_by"]),
            _timestamp(row["expires_at"]),
            _timestamp(row["created_at"]),
            _timestamp(row["updated_at"]),
        ),
    )


def _record(index: int, *, status: MemoryStatus = MemoryStatus.CANDIDATE) -> MemoryRecord:
    return MemoryRecord(
        memory_id=_memory_id(index),
        memory_type=MemoryType.PREFERENCE,
        text=f"Keep test {index} deterministic.",
        confidence=0.9,
        status=status,
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        created_at=NOW,
        updated_at=NOW,
    )


def _memory_id(index: int) -> MemoryId:
    return MemoryId(UUID(int=index))


def _management() -> GovernedMemoryManagementContext:
    return GovernedMemoryManagementContext(
        operation_id="verify-import",
        operator="test",
        reason="verify tombstone",
    )


def _value(value: object) -> object:
    return getattr(value, "value", value)


def _timestamp(value: object) -> str | None:
    if value is None:
        return None
    assert isinstance(value, datetime)
    return value.isoformat()
