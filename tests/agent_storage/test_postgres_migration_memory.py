from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from agent_storage.postgres import (
    MigrationImportError,
    apply_postgres_migrations,
    export_sqlite_snapshot,
    import_sqlite_event_snapshot,
    write_sqlite_snapshot,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def isolated_dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"test_migration_memory_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(dsn)
    yield dsn
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_event_import_replays_governed_memory_authority(
    isolated_dsn: str, tmp_path: Path
) -> None:
    source = tmp_path / "source.sqlite"
    _create_source(source, confidence=0.8)
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(
        export_sqlite_snapshot(source, table_names=("memory_records",)), snapshot_dir
    )

    report = import_sqlite_event_snapshot(
        snapshot_dir,
        isolated_dsn,
        deployment_namespace="tenant-a",
        importer_identity="zebra-postgres-migration-v1",
    )

    assert report.memory_count == 1
    with psycopg.connect(isolated_dsn) as connection:
        row = connection.execute(
            """SELECT deployment_namespace, memory_type, status, repo_id,
                text, length(creation_key), length(content_digest), length(provenance_digest)
            FROM governed_memory_records"""
        ).fetchone()
    assert row == (
        "tenant-a",
        "preference",
        "candidate",
        "zebra-agent",
        "Keep migration deterministic.",
        64,
        64,
        64,
    )


def test_event_import_rejects_invalid_memory_before_any_write(
    isolated_dsn: str, tmp_path: Path
) -> None:
    source = tmp_path / "source.sqlite"
    _create_source(source, confidence=2.0)
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(
        export_sqlite_snapshot(source, table_names=("memory_records",)), snapshot_dir
    )

    with pytest.raises(MigrationImportError, match="Memory"):
        import_sqlite_event_snapshot(
            snapshot_dir,
            isolated_dsn,
            deployment_namespace="tenant-a",
            importer_identity="zebra-postgres-migration-v1",
        )
    with psycopg.connect(isolated_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM governed_memory_records").fetchone() == (0,)


def _create_source(path: Path, *, confidence: float) -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC).isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE memory_records (
                memory_id TEXT, memory_type TEXT, text TEXT, confidence REAL,
                status TEXT, visibility TEXT, tenant_id TEXT, user_id TEXT,
                repo_id TEXT, source_session_id TEXT, source_event_start INTEGER,
                source_event_end INTEGER, source_commit_sha TEXT, superseded_by TEXT,
                expires_at TEXT, created_at TEXT, updated_at TEXT
            )"""
        )
        connection.execute(
            "INSERT INTO memory_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "00000000-0000-0000-0000-000000000001",
                "preference",
                "Keep migration deterministic.",
                confidence,
                "candidate",
                "repo",
                None,
                None,
                "zebra-agent",
                None,
                None,
                None,
                None,
                None,
                None,
                now,
                now,
            ),
        )
