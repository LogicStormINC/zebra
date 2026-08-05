from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_storage import SQLiteDeliveryAuditStore, SQLiteEventStore
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
    schema = f"test_migration_delivery_audit_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(dsn)
    yield dsn
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_event_import_replays_delivery_audit_in_source_order(
    isolated_dsn: str, tmp_path: Path
) -> None:
    source = tmp_path / "source.sqlite"
    session_id = new_session_id()
    event_store = SQLiteEventStore(source)
    audit_store = SQLiteDeliveryAuditStore(source)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "audit import"},
        )
    )
    audit_store.append(
        DeliveryAuditRecord(
            session_id=session_id,
            action="session.commit",
            status="committed",
            status_code=200,
            policy_profile="cloud-safe",
            idempotency_key="audit-1",
            result_metadata={"ordinal": 1},
            created_at=datetime(2026, 8, 5, 12, 0, tzinfo=UTC),
        )
    )
    audit_store.append(
        DeliveryAuditRecord(
            session_id=session_id,
            action="session.pull_request",
            status="failed",
            status_code=409,
            policy_profile=None,
            idempotency_key=None,
            result_metadata={"ordinal": 2},
            created_at=datetime(2026, 8, 5, 12, 1, tzinfo=UTC),
        )
    )
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(
        export_sqlite_snapshot(
            source,
            table_names=("session_events", "delivery_audit_records"),
            include_rowids=("delivery_audit_records",),
        ),
        snapshot_dir,
    )

    report = import_sqlite_event_snapshot(
        snapshot_dir,
        isolated_dsn,
        deployment_namespace="tenant-a",
        importer_identity="zebra-postgres-migration-v1",
    )

    assert report.delivery_audit_count == 2
    with psycopg.connect(isolated_dsn) as connection:
        rows = connection.execute(
            """SELECT action, status, result_metadata->>'ordinal'
            FROM control_plane_delivery_audit_records ORDER BY audit_id"""
        ).fetchall()
    assert rows == [("session.commit", "committed", "1"), ("session.pull_request", "failed", "2")]


def test_event_import_rejects_delivery_audit_without_snapshot_rowid(
    isolated_dsn: str, tmp_path: Path
) -> None:
    source = tmp_path / "source.sqlite"
    session_id = new_session_id()
    event_store = SQLiteEventStore(source)
    audit_store = SQLiteDeliveryAuditStore(source)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "audit import"},
        )
    )
    audit_store.append(
        DeliveryAuditRecord(
            session_id=session_id,
            action="session.commit",
            status="committed",
            status_code=200,
            policy_profile=None,
            idempotency_key=None,
            result_metadata={},
            created_at=datetime(2026, 8, 5, tzinfo=UTC),
        )
    )
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(
        export_sqlite_snapshot(source, table_names=("session_events", "delivery_audit_records")),
        snapshot_dir,
    )

    with pytest.raises(MigrationImportError, match="rowid"):
        import_sqlite_event_snapshot(
            snapshot_dir,
            isolated_dsn,
            deployment_namespace="tenant-a",
            importer_identity="zebra-postgres-migration-v1",
        )
    with psycopg.connect(isolated_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM control_plane_delivery_audit_records"
        ).fetchone() == (0,)
