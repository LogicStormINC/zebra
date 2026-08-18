from __future__ import annotations

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
from agent_storage.postgres.migration_legacy_artifact import (
    ArtifactQuarantineError,
    build_artifact_quarantine,
    load_artifact_quarantine,
    write_artifact_quarantine,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo

_ARTIFACT_COLUMNS = (
    "artifact_id",
    "session_id",
    "kind",
    "mime_type",
    "uri",
    "access_uri",
    "sha256",
    "size_bytes",
    "lifecycle_status",
    "retained_until",
    "pruned_at",
    "created_at",
)


def _create_legacy_artifact_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE artifact_payloads (
            artifact_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            uri TEXT NOT NULL,
            access_uri TEXT,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            lifecycle_status TEXT NOT NULL,
            retained_until TEXT,
            pruned_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )


def _insert_legacy_artifact(
    connection: sqlite3.Connection, artifact_id: str, session_id: str
) -> None:
    connection.execute(
        """
        INSERT INTO artifact_payloads (
            artifact_id, session_id, kind, mime_type, uri, access_uri,
            sha256, size_bytes, lifecycle_status, retained_until, pruned_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            session_id,
            "tool-output",
            "text/plain",
            f"artifact://{artifact_id}",
            f"file:///tmp/{artifact_id}.txt",
            "a" * 64,
            12,
            "active",
            "2026-08-06T00:00:00+00:00",
            None,
            "2026-08-05T00:00:00+00:00",
        ),
    )


def _legacy_source(path: Path, *, session_id: str | None = None) -> str:
    effective_session_id = session_id or str(new_session_id())
    with sqlite3.connect(path) as connection:
        _create_legacy_artifact_table(connection)
        # Insertion order must not become migration order.
        _insert_legacy_artifact(
            connection, "00000000-0000-0000-0000-000000000002", effective_session_id
        )
        _insert_legacy_artifact(
            connection, "00000000-0000-0000-0000-000000000001", effective_session_id
        )
    return effective_session_id


def test_artifact_quarantine_round_trip_is_manifest_bound(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _legacy_source(source)
    snapshot = export_sqlite_snapshot(source, table_names=("artifact_payloads",))

    quarantine = build_artifact_quarantine(snapshot)
    assert quarantine.manifest.source_snapshot_manifest_sha256 == snapshot.manifest.digest
    assert quarantine.manifest.record_count == 2
    assert quarantine.manifest.source_table == "artifact_payloads"
    assert quarantine.manifest.reason == "missing_cloud_authority_bindings"
    assert quarantine.manifest.disposition == "quarantine_rebuild_required"
    assert "reservation_fencing_token" in quarantine.manifest.unavailable_fields
    assert [record.values[0] for record in quarantine.records] == [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]
    assert quarantine.records[0].columns == _ARTIFACT_COLUMNS

    output = tmp_path / "quarantine"
    write_artifact_quarantine(quarantine, output)
    assert load_artifact_quarantine(output) == quarantine


def test_artifact_quarantine_tampering_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _legacy_source(source)
    output = tmp_path / "quarantine"
    write_artifact_quarantine(
        build_artifact_quarantine(
            export_sqlite_snapshot(source, table_names=("artifact_payloads",))
        ),
        output,
    )
    records = (output / "records.jsonl").read_text(encoding="utf-8")
    (output / "records.jsonl").write_text(
        records.replace("tool-output", "tampered-output", 1), encoding="utf-8"
    )

    with pytest.raises(ArtifactQuarantineError, match="checksum"):
        load_artifact_quarantine(output)


def test_artifact_quarantine_rejects_nonfinite_json(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _legacy_source(source)
    output = tmp_path / "quarantine"
    write_artifact_quarantine(
        build_artifact_quarantine(
            export_sqlite_snapshot(source, table_names=("artifact_payloads",))
        ),
        output,
    )
    records = (output / "records.jsonl").read_text(encoding="utf-8")
    (output / "records.jsonl").write_text(
        records.replace(',12,"active"', ',NaN,"active"', 1), encoding="utf-8"
    )

    with pytest.raises(ArtifactQuarantineError, match="malformed"):
        load_artifact_quarantine(output)


def test_artifact_quarantine_requires_source_table(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT NOT NULL)")
        connection.execute("INSERT INTO unrelated VALUES ('no artifact')")

    with pytest.raises(ArtifactQuarantineError, match="artifact_payloads"):
        build_artifact_quarantine(export_sqlite_snapshot(source))


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def isolated_dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"test_migration_legacy_artifact_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(dsn)
    yield dsn
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_legacy_artifact_preflight_is_zero_write(
    isolated_dsn: str, tmp_path: Path
) -> None:
    source = tmp_path / "source.sqlite"
    session_id = new_session_id()
    event_store = SQLiteEventStore(source)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "legacy artifact quarantine"},
        )
    )
    _legacy_source(source, session_id=str(session_id))
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(
        export_sqlite_snapshot(source, table_names=("session_events", "artifact_payloads")),
        snapshot_dir,
    )
    quarantine_dir = tmp_path / "quarantine"
    write_artifact_quarantine(
        build_artifact_quarantine(
            export_sqlite_snapshot(source, table_names=("session_events", "artifact_payloads"))
        ),
        quarantine_dir,
    )

    with pytest.raises(MigrationImportError, match="artifact_payloads"):
        import_sqlite_event_snapshot(
            snapshot_dir,
            isolated_dsn,
            deployment_namespace="tenant-a",
            importer_identity="zebra-postgres-migration-v1",
        )

    assert load_artifact_quarantine(quarantine_dir).manifest.source_table == "artifact_payloads"
    with psycopg.connect(isolated_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM session_events").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM artifact_payload_metadata"
        ).fetchone() == (0,)
