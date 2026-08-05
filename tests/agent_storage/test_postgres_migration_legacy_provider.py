from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_storage import SQLiteEventStore
from agent_storage.postgres import (
    MigrationImportError,
    apply_postgres_migrations,
    export_sqlite_snapshot,
    import_sqlite_event_snapshot,
    write_sqlite_snapshot,
)
from agent_storage.postgres.migration_legacy_provider import (
    ProviderQuarantineError,
    build_provider_quarantine,
    load_provider_quarantine,
    write_provider_quarantine,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo

_PROVIDER_COLUMNS = (
    "artifact_id",
    "tenant_id",
    "session_id",
    "reference_id",
    "provider",
    "model_name",
    "capability_version",
    "source_hash",
    "opaque_payload",
    "payload_sha256",
    "size_bytes",
    "created_at",
    "expires_at",
    "deleted_at",
)


def _create_legacy_provider_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE provider_continuation_artifacts (
            artifact_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            reference_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            model_name TEXT NOT NULL,
            capability_version TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            opaque_payload BLOB,
            payload_sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            deleted_at TEXT,
            UNIQUE (tenant_id, provider, reference_id)
        )
        """
    )


def _insert_legacy_provider(
    connection: sqlite3.Connection,
    artifact_id: str,
    session_id: str,
    reference_id: str,
    payload: bytes,
    deleted_at: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO provider_continuation_artifacts (
            artifact_id, tenant_id, session_id, reference_id, provider,
            model_name, capability_version, source_hash, opaque_payload,
            payload_sha256, size_bytes, created_at, expires_at, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            "tenant-a",
            session_id,
            reference_id,
            "openai",
            "gpt-4.1",
            "1",
            f"source-{reference_id}",
            payload,
            hashlib.sha256(payload).hexdigest(),
            len(payload),
            "2026-08-05T00:00:00+00:00",
            "2026-08-06T00:00:00+00:00",
            deleted_at,
        ),
    )


def _legacy_source(path: Path, *, session_id: str | None = None) -> str:
    effective_session_id = session_id or str(new_session_id())
    with sqlite3.connect(path) as connection:
        _create_legacy_provider_table(connection)
        # Insertion order must not become migration order.
        _insert_legacy_provider(
            connection,
            "artifact-z",
            effective_session_id,
            "reference-z",
            b"opaque-z",
            None,
        )
        _insert_legacy_provider(
            connection,
            "artifact-a",
            effective_session_id,
            "reference-a",
            b"opaque-a",
            "2026-08-05T12:00:00+00:00",
        )
    return effective_session_id


def test_provider_quarantine_round_trip_is_manifest_bound(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _legacy_source(source)
    snapshot = export_sqlite_snapshot(source, table_names=("provider_continuation_artifacts",))

    quarantine = build_provider_quarantine(snapshot)
    assert quarantine.manifest.source_snapshot_manifest_sha256 == snapshot.manifest.digest
    assert quarantine.manifest.record_count == 2
    assert quarantine.manifest.source_table == "provider_continuation_artifacts"
    assert quarantine.manifest.reason == "missing_cloud_authority_bindings"
    assert quarantine.manifest.disposition == "quarantine_rebuild_required"
    assert "selection_event_id" in quarantine.manifest.unavailable_fields
    assert "accepted_lease_fencing_token" in quarantine.manifest.unavailable_fields
    assert [record.values[0] for record in quarantine.records] == [
        "artifact-a",
        "artifact-z",
    ]
    assert quarantine.records[0].columns == _PROVIDER_COLUMNS
    assert quarantine.records[0].values[8] == {"$bytes": "b3BhcXVlLWE="}

    output = tmp_path / "quarantine"
    write_provider_quarantine(quarantine, output)
    assert load_provider_quarantine(output) == quarantine


def test_provider_quarantine_tampering_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _legacy_source(source)
    output = tmp_path / "quarantine"
    write_provider_quarantine(
        build_provider_quarantine(
            export_sqlite_snapshot(source, table_names=("provider_continuation_artifacts",))
        ),
        output,
    )
    records = (output / "records.jsonl").read_text(encoding="utf-8")
    (output / "records.jsonl").write_text(
        records.replace("tenant-a", "tenant-b", 1), encoding="utf-8"
    )

    with pytest.raises(ProviderQuarantineError, match="checksum"):
        load_provider_quarantine(output)


def test_provider_quarantine_rejects_nonfinite_json(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _legacy_source(source)
    output = tmp_path / "quarantine"
    write_provider_quarantine(
        build_provider_quarantine(
            export_sqlite_snapshot(source, table_names=("provider_continuation_artifacts",))
        ),
        output,
    )
    records = (output / "records.jsonl").read_text(encoding="utf-8")
    (output / "records.jsonl").write_text(
        records.replace(',8,"2026-', ',NaN,"2026-', 1), encoding="utf-8"
    )

    with pytest.raises(ProviderQuarantineError, match="malformed"):
        load_provider_quarantine(output)


def test_provider_quarantine_requires_source_table(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT NOT NULL)")
        connection.execute("INSERT INTO unrelated VALUES ('no provider')")

    with pytest.raises(ProviderQuarantineError, match="provider_continuation_artifacts"):
        build_provider_quarantine(export_sqlite_snapshot(source))


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def isolated_dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"test_migration_legacy_provider_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(dsn)
    yield dsn
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_legacy_provider_preflight_is_zero_write(isolated_dsn: str, tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    session_id = new_session_id()
    event_store = SQLiteEventStore(source)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "legacy provider quarantine"},
        )
    )
    _legacy_source(source, session_id=str(session_id))
    snapshot = export_sqlite_snapshot(
        source, table_names=("session_events", "provider_continuation_artifacts")
    )
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(snapshot, snapshot_dir)
    quarantine_dir = tmp_path / "quarantine"
    write_provider_quarantine(build_provider_quarantine(snapshot), quarantine_dir)

    with pytest.raises(MigrationImportError, match="provider_continuation_artifacts"):
        import_sqlite_event_snapshot(
            snapshot_dir,
            isolated_dsn,
            deployment_namespace="tenant-a",
            importer_identity="zebra-postgres-migration-v1",
        )

    assert (
        load_provider_quarantine(quarantine_dir).manifest.source_table
        == "provider_continuation_artifacts"
    )
    with psycopg.connect(isolated_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM session_events").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM provider_continuation_artifacts"
        ).fetchone() == (0,)
