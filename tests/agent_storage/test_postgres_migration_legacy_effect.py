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
from agent_storage.postgres.migration_legacy_effect import (
    EffectQuarantineError,
    build_effect_quarantine,
    load_effect_quarantine,
    write_effect_quarantine,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo

_EFFECT_COLUMNS = (
    "root_session_id",
    "ledger_key",
    "identity_json",
    "status",
    "attempt",
    "result_json",
    "created_at",
    "updated_at",
)


def _create_legacy_effect_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE effect_ledger (
            root_session_id TEXT NOT NULL,
            ledger_key TEXT NOT NULL,
            identity_json TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            result_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (root_session_id, ledger_key)
        )
        """
    )


def _insert_legacy_effect(
    connection: sqlite3.Connection,
    root_session_id: str,
    ledger_key: str,
    status: str,
    result_json: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO effect_ledger (
            root_session_id, ledger_key, identity_json, status, attempt,
            result_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            root_session_id,
            ledger_key,
            '{"authority_scope_hash":"scope","tool_name":"shell",'
            '"operation_kind":"command","target_hash":"target",'
            '"canonical_effect_hash":"effect"}',
            status,
            1,
            result_json,
            "2026-08-05T00:00:00+00:00",
            "2026-08-05T00:01:00+00:00",
        ),
    )


def _legacy_source(path: Path, *, root_session_id: str | None = None) -> str:
    effective_session_id = root_session_id or str(new_session_id())
    with sqlite3.connect(path) as connection:
        _create_legacy_effect_table(connection)
        # Insertion order must not become migration order.
        _insert_legacy_effect(
            connection,
            effective_session_id,
            "effect-z",
            "uncertain",
            None,
        )
        _insert_legacy_effect(
            connection,
            effective_session_id,
            "effect-a",
            "succeeded",
            '{"output":"ok","status":"succeeded"}',
        )
    return effective_session_id


def test_effect_quarantine_round_trip_is_manifest_bound(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _legacy_source(source)
    snapshot = export_sqlite_snapshot(source, table_names=("effect_ledger",))

    quarantine = build_effect_quarantine(snapshot)
    assert quarantine.manifest.source_snapshot_manifest_sha256 == snapshot.manifest.digest
    assert quarantine.manifest.record_count == 2
    assert quarantine.manifest.source_table == "effect_ledger"
    assert quarantine.manifest.reason == "missing_cloud_authority_bindings"
    assert quarantine.manifest.disposition == "quarantine_rebuild_required"
    assert "intent_event_id" in quarantine.manifest.unavailable_fields
    assert [record.values[1] for record in quarantine.records] == [
        "effect-a",
        "effect-z",
    ]
    assert quarantine.records[0].columns == _EFFECT_COLUMNS

    output = tmp_path / "quarantine"
    write_effect_quarantine(quarantine, output)
    assert load_effect_quarantine(output) == quarantine


def test_effect_quarantine_tampering_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _legacy_source(source)
    output = tmp_path / "quarantine"
    write_effect_quarantine(
        build_effect_quarantine(export_sqlite_snapshot(source, table_names=("effect_ledger",))),
        output,
    )
    records = (output / "records.jsonl").read_text(encoding="utf-8")
    (output / "records.jsonl").write_text(
        records.replace('"uncertain"', '"succeeded"', 1), encoding="utf-8"
    )

    with pytest.raises(EffectQuarantineError, match="checksum"):
        load_effect_quarantine(output)


def test_effect_quarantine_rejects_nonfinite_json(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _legacy_source(source)
    output = tmp_path / "quarantine"
    write_effect_quarantine(
        build_effect_quarantine(export_sqlite_snapshot(source, table_names=("effect_ledger",))),
        output,
    )
    records = (output / "records.jsonl").read_text(encoding="utf-8")
    (output / "records.jsonl").write_text(
        records.replace(',"uncertain",1,null,', ',"uncertain",NaN,null,', 1),
        encoding="utf-8",
    )

    with pytest.raises(EffectQuarantineError, match="malformed"):
        load_effect_quarantine(output)


def test_effect_quarantine_requires_source_table(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT NOT NULL)")
        connection.execute("INSERT INTO unrelated VALUES ('no effect')")

    with pytest.raises(EffectQuarantineError, match="effect_ledger"):
        build_effect_quarantine(export_sqlite_snapshot(source))


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def isolated_dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"test_migration_legacy_effect_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(dsn)
    yield dsn
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_legacy_effect_preflight_is_zero_write(isolated_dsn: str, tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    session_id = new_session_id()
    event_store = SQLiteEventStore(source)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "legacy effect quarantine"},
        )
    )
    _legacy_source(source, root_session_id=str(session_id))
    snapshot = export_sqlite_snapshot(source, table_names=("session_events", "effect_ledger"))
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(snapshot, snapshot_dir)
    quarantine_dir = tmp_path / "quarantine"
    write_effect_quarantine(build_effect_quarantine(snapshot), quarantine_dir)

    with pytest.raises(MigrationImportError, match="effect_ledger"):
        import_sqlite_event_snapshot(
            snapshot_dir,
            isolated_dsn,
            deployment_namespace="tenant-a",
            importer_identity="zebra-postgres-migration-v1",
        )

    assert load_effect_quarantine(quarantine_dir).manifest.source_table == "effect_ledger"
    with psycopg.connect(isolated_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM session_events").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM effect_outbox").fetchone() == (0,)
