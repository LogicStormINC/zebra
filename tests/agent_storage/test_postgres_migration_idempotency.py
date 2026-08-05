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
    schema = f"test_migration_idempotency_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(dsn)
    yield dsn
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_event_import_replays_namespace_idempotency_receipt(
    isolated_dsn: str, tmp_path: Path
) -> None:
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute(
            """CREATE TABLE idempotency_records (
                action TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL, status_code INTEGER NOT NULL,
                response_body TEXT NOT NULL, created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO idempotency_records VALUES (?, ?, ?, ?, ?, ?)",
            (
                "session.create", "receipt-1", "request-hash", 201,
                '{"session_id":"00000000-0000-0000-0000-000000000001"}',
                datetime(2026, 8, 5, tzinfo=UTC).isoformat(),
            ),
        )
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(
        export_sqlite_snapshot(source, table_names=("idempotency_records",)),
        snapshot_dir,
    )

    report = import_sqlite_event_snapshot(
        snapshot_dir, isolated_dsn, deployment_namespace="tenant-a",
        importer_identity="zebra-postgres-migration-v1",
    )

    assert report.idempotency_count == 1
    with psycopg.connect(isolated_dsn) as connection:
        row = connection.execute(
            """SELECT deployment_namespace, action, idempotency_key,
                status_code, response_body->>'session_id'
            FROM control_plane_idempotency_records"""
        ).fetchone()
        assert row == (
            "tenant-a", "session.create", "receipt-1", 201,
            "00000000-0000-0000-0000-000000000001",
        )


def test_event_import_rejects_non_object_idempotency_receipt(
    isolated_dsn: str, tmp_path: Path
) -> None:
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute(
            """CREATE TABLE idempotency_records (
                action TEXT, idempotency_key TEXT, request_hash TEXT,
                status_code INTEGER, response_body TEXT, created_at TEXT
            )"""
        )
        connection.execute(
            "INSERT INTO idempotency_records VALUES (?, ?, ?, ?, ?, ?)",
            (
                "session.create", "receipt-1", "request-hash", 201, "[]",
                datetime(2026, 8, 5, tzinfo=UTC).isoformat(),
            ),
        )
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(
        export_sqlite_snapshot(source, table_names=("idempotency_records",)),
        snapshot_dir,
    )

    with pytest.raises(MigrationImportError, match="response_body"):
        import_sqlite_event_snapshot(
            snapshot_dir, isolated_dsn, deployment_namespace="tenant-a",
            importer_identity="zebra-postgres-migration-v1",
        )
    with psycopg.connect(isolated_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM control_plane_idempotency_records"
        ).fetchone() == (0,)
