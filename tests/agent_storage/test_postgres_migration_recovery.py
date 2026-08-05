from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.contracts.events import ContextCapsuleCreatedPayload
from agent_core.domain.context_capsule import ContextCapsule, ContextSourceEventRange
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_storage import SQLiteContextLifecycleStore, SQLiteEventStore
from agent_storage.postgres import (
    CutoverConflictError,
    MigrationImportError,
    PostgresCutoverStore,
    SnapshotIntegrityError,
    apply_postgres_migrations,
    export_sqlite_snapshot,
    import_sqlite_event_snapshot,
    load_sqlite_snapshot,
    write_sqlite_snapshot,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo


def test_sqlite_snapshot_is_canonical_and_read_only(tmp_path: Path) -> None:
    database = tmp_path / "source.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE facts (name TEXT NOT NULL, payload BLOB)")
        connection.execute("INSERT INTO facts VALUES (?, ?)", ("é", b"one"))
        connection.execute("INSERT INTO facts VALUES (?, ?)", ("e\u0301", b"two"))
        connection.execute("PRAGMA user_version = 7")

    first = export_sqlite_snapshot(database)
    output = tmp_path / "snapshot"
    write_sqlite_snapshot(first, output)
    second = export_sqlite_snapshot(database)

    assert first == second
    assert first.manifest.record_count == 2
    assert first.manifest.table_counts == (("facts", 2),)
    assert first.records[0].values[0] == "é"
    assert load_sqlite_snapshot(output) == first
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (7,)


def test_snapshot_tampering_fails_before_import(tmp_path: Path) -> None:
    database = tmp_path / "source.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE facts (value TEXT NOT NULL)")
        connection.execute("INSERT INTO facts VALUES ('original')")
    output = tmp_path / "snapshot"
    write_sqlite_snapshot(export_sqlite_snapshot(database), output)
    records = (output / "records.jsonl").read_text(encoding="utf-8")
    (output / "records.jsonl").write_text(records.replace("original", "changed"), encoding="utf-8")

    with pytest.raises(SnapshotIntegrityError, match="checksum"):
        load_sqlite_snapshot(output)


def test_event_import_rebuilds_projection_after_events(isolated_dsn: str, tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    event_store = SQLiteEventStore(source)
    session_id = new_session_id()
    created = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "Imported session"},
    )
    message = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": "replay me"},
    )
    event_store.append(created)
    event_store.append(message)
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(
        export_sqlite_snapshot(source, table_names=("session_events",)),
        snapshot_dir,
    )

    report = import_sqlite_event_snapshot(
        snapshot_dir,
        isolated_dsn,
        deployment_namespace="tenant-a",
        importer_identity="zebra-postgres-migration-v1",
    )

    assert report.event_count == 2
    assert report.projection_count == 1
    with psycopg.connect(isolated_dsn) as connection:
        event_count = connection.execute("SELECT count(*) FROM session_events").fetchone()
        assert event_count is not None
        assert event_count[0] == 2
        row = connection.execute(
            "SELECT title, current_sequence FROM session_projections"
        ).fetchone()
        assert row is not None
        assert row[0] == "Imported session"
        assert row[1] == 1

    with pytest.raises(MigrationImportError, match="empty"):
        import_sqlite_event_snapshot(
            snapshot_dir,
            isolated_dsn,
            deployment_namespace="tenant-a",
            importer_identity="zebra-postgres-migration-v1",
        )


def test_event_import_rebuilds_workspace_projection(isolated_dsn: str, tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    event_store = SQLiteEventStore(source)
    session_id = new_session_id()
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Workspace import"},
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.USER,
            payload={
                "title": "Workspace import",
                "user_input": "restore workspace",
                "workspace_root": "/workspaces/imported",
            },
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            actor=EventActor.TOOL,
            idempotency_key="tool-import-1",
            payload={
                "attempt_number": 1,
                "tool_name": "shell",
                "status": "succeeded",
                "output": "ok",
                "metadata": {},
            },
        )
    )
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(
        export_sqlite_snapshot(source, table_names=("session_events",)),
        snapshot_dir,
    )

    report = import_sqlite_event_snapshot(
        snapshot_dir,
        isolated_dsn,
        deployment_namespace="tenant-a",
        importer_identity="zebra-postgres-migration-v1",
    )

    assert report.workspace_count == 1
    assert report.model_tool_projection_count == 1
    assert report.task_count == 1
    with psycopg.connect(isolated_dsn) as connection:
        row = connection.execute(
            "SELECT workspace_root, current_sequence, status FROM workspace_projections"
        ).fetchone()
        assert row is not None
        assert row[0] == "/workspaces/imported"
        assert row[1] == 2
        assert row[2] == "prepared"
        tool = connection.execute(
            "SELECT tool_name, status, output FROM tool_run_projections"
        ).fetchone()
        assert tool is not None
        assert tuple(tool) == ("shell", "succeeded", "ok")
        task = connection.execute(
            "SELECT task_id, active_segment_id FROM agent_tasks"
        ).fetchone()
        assert task is not None
        assert task[0] == task[1]


@pytest.mark.parametrize(
    "legacy_authority_table",
    ("artifact_payloads", "effect_ledger", "provider_continuation_artifacts"),
)
def test_event_import_rejects_legacy_authority_tables_before_writes(
    isolated_dsn: str,
    tmp_path: Path,
    legacy_authority_table: str,
) -> None:
    """Legacy rows cannot be promoted without their cloud authority bindings."""
    source = tmp_path / f"{legacy_authority_table}.sqlite"
    event_store = SQLiteEventStore(source)
    event_store.append(
        SessionEvent.create(
            session_id=new_session_id(),
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "blocked legacy authority"},
        )
    )
    with sqlite3.connect(source) as connection:
        connection.execute(
            f'CREATE TABLE "{legacy_authority_table}" (marker TEXT NOT NULL)'
        )
        connection.execute(
            f'INSERT INTO "{legacy_authority_table}" VALUES (?)',
            ("legacy-row",),
        )
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(
        export_sqlite_snapshot(source, table_names=("session_events", legacy_authority_table)),
        snapshot_dir,
    )

    with pytest.raises(MigrationImportError, match=legacy_authority_table):
        import_sqlite_event_snapshot(
            snapshot_dir,
            isolated_dsn,
            deployment_namespace="tenant-a",
            importer_identity="zebra-postgres-migration-v1",
        )
    with psycopg.connect(isolated_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM session_events").fetchone() == (0,)


def test_event_import_requires_restricted_identity(isolated_dsn: str, tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE session_events (event_id TEXT)")
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(export_sqlite_snapshot(source), snapshot_dir)

    with pytest.raises(MigrationImportError, match="identity"):
        import_sqlite_event_snapshot(
            snapshot_dir,
            isolated_dsn,
            deployment_namespace="tenant-a",
            importer_identity="runtime",
        )


def test_event_import_rebuilds_context_capsule_and_active_pointer(
    isolated_dsn: str, tmp_path: Path
) -> None:
    source = tmp_path / "source.sqlite"
    event_store = SQLiteEventStore(source)
    SQLiteContextLifecycleStore(source)
    session_id = new_session_id()
    created_at = datetime(2026, 8, 5, tzinfo=UTC)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Context import"},
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.USER,
            payload={
                "title": "Context import",
                "user_input": "restore context",
                "workspace_root": "/workspaces/context-import",
            },
            created_at=created_at,
        )
    )
    capsule = ContextCapsule(
        capsule_id="capsule-import",
        objective="Resume context import",
        immediate_next="continue",
        source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=1),
        source_hash="a" * 64,
        confidence=1.0,
        created_at=created_at,
    )
    compaction = SessionEvent.create(
        session_id=session_id,
        sequence=2,
        event_type=EventType.CONTEXT_COMPACTED,
        actor=EventActor.SYSTEM,
        payload={
            "attempt_number": 1,
            "before_tokens": 10,
            "after_tokens": 5,
            "removed_message_count": 1,
            "retained_message_count": 1,
            "within_budget": True,
            "provenance": "migration-test",
            "capsule": capsule.model_dump(mode="json"),
        },
        created_at=created_at,
    )
    artifact_id = uuid4()
    assert capsule.source_event_range is not None
    capsule_event = SessionEvent.create(
        session_id=session_id,
        sequence=3,
        event_type=EventType.CONTEXT_CAPSULE_CREATED,
        actor=EventActor.SYSTEM,
        payload=ContextCapsuleCreatedPayload(
            capsule_id=capsule.capsule_id,
            artifact_id=str(artifact_id),
            schema_version=capsule.version,
            source_hash=capsule.source_hash,
            source_event_range=capsule.source_event_range,
        ).model_dump(mode="json"),
        created_at=created_at,
    )
    for event in (compaction, capsule_event):
        event_store.append(event)
    payload = capsule.model_dump_json().encode("utf-8")
    with sqlite3.connect(source) as connection:
        connection.execute(
            """INSERT INTO context_capsule_artifacts (
                capsule_id, artifact_id, session_id, payload, payload_sha256,
                source_hash, created_at, event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                capsule.capsule_id,
                str(artifact_id),
                str(session_id),
                payload,
                hashlib.sha256(payload).hexdigest(),
                capsule.source_hash,
                created_at.isoformat(),
                str(capsule_event.event_id),
            ),
        )
        connection.execute(
            """INSERT INTO active_context_projections (
                session_id, capsule_id, artifact_id, source_hash, event_sequence, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                str(session_id),
                capsule.capsule_id,
                str(artifact_id),
                capsule.source_hash,
                capsule_event.sequence,
                created_at.isoformat(),
            ),
        )
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(
        export_sqlite_snapshot(
            source,
            table_names=(
                "session_events",
                "context_capsule_artifacts",
                "active_context_projections",
            ),
        ),
        snapshot_dir,
    )

    report = import_sqlite_event_snapshot(
        snapshot_dir,
        isolated_dsn,
        deployment_namespace="tenant-a",
        importer_identity="zebra-postgres-migration-v1",
    )

    assert report.context_capsule_count == 1
    assert report.active_context_count == 1
    with psycopg.connect(isolated_dsn) as connection:
        row = connection.execute(
            "SELECT capsule_id, artifact_id, event_sequence FROM active_context_projections"
        ).fetchone()
        assert row is not None
        assert row[0] == capsule.capsule_id
        assert str(row[1]) == str(artifact_id)
        assert row[2] == capsule_event.sequence


def test_event_import_rejects_any_nonempty_target(
    isolated_dsn: str, tmp_path: Path
) -> None:
    source = tmp_path / "source.sqlite"
    SQLiteEventStore(source).append(
        SessionEvent.create(
            session_id=new_session_id(),
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Occupied target"},
        )
    )
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(export_sqlite_snapshot(source), snapshot_dir)
    with psycopg.connect(isolated_dsn) as connection:
        connection.execute("CREATE TABLE unrelated_state (value TEXT NOT NULL)")
        connection.execute("INSERT INTO unrelated_state VALUES ('occupied')")

    with pytest.raises(MigrationImportError, match="empty"):
        import_sqlite_event_snapshot(
            snapshot_dir,
            isolated_dsn,
            deployment_namespace="tenant-a",
            importer_identity="zebra-postgres-migration-v1",
        )


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def isolated_dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"test_migration_recovery_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(dsn)
    yield dsn
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _digest(value: str = "snapshot") -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_cutover_lifecycle_has_one_active_record(isolated_dsn: str) -> None:
    digest = _digest()
    store = PostgresCutoverStore(isolated_dsn, deployment_namespace="tenant-a")
    cutover_id = store.prepare(manifest_sha256=digest)
    store.verify(cutover_id, manifest_sha256=digest)
    store.activate(cutover_id, manifest_sha256=digest)

    competing_id = store.prepare(manifest_sha256=digest)
    store.verify(competing_id, manifest_sha256=digest)
    with pytest.raises(CutoverConflictError, match="active"):
        store.activate(competing_id, manifest_sha256=digest)

    with psycopg.connect(isolated_dsn) as connection:
        row = connection.execute(
            "SELECT count(*) FROM control_plane_cutovers WHERE state = 'active'"
        ).fetchone()
        assert row is not None
        assert row[0] == 1


def test_cutover_namespace_and_digest_mismatch_fail_closed(isolated_dsn: str) -> None:
    digest = _digest()
    store = PostgresCutoverStore(isolated_dsn, deployment_namespace="tenant-a")
    cutover_id = store.prepare(manifest_sha256=digest)
    store.verify(cutover_id, manifest_sha256=digest)
    other = PostgresCutoverStore(isolated_dsn, deployment_namespace="tenant-b")
    with pytest.raises(CutoverConflictError):
        other.activate(cutover_id, manifest_sha256=digest)
    with pytest.raises(CutoverConflictError):
        store.activate(cutover_id, manifest_sha256=_digest("different"))


def test_guarded_write_does_not_call_action_when_not_active(isolated_dsn: str) -> None:
    digest = _digest()
    store = PostgresCutoverStore(isolated_dsn, deployment_namespace="tenant-a")
    cutover_id = store.prepare(manifest_sha256=digest)
    called = False

    def action(_: object) -> None:
        nonlocal called
        called = True

    with pytest.raises(CutoverConflictError, match="active"):
        store.run_guarded(cutover_id, digest, action)
    assert not called


def test_guarded_write_rolls_back_on_action_failure(isolated_dsn: str) -> None:
    digest = _digest()
    store = PostgresCutoverStore(isolated_dsn, deployment_namespace="tenant-a")
    cutover_id = store.prepare(manifest_sha256=digest)
    store.verify(cutover_id, manifest_sha256=digest)
    store.activate(cutover_id, manifest_sha256=digest)
    with psycopg.connect(isolated_dsn) as connection:
        connection.execute("CREATE TABLE write_probe (value TEXT NOT NULL)")

    def action(connection: psycopg.Connection[dict[str, object]]) -> None:
        connection.execute("INSERT INTO write_probe VALUES ('uncommitted')")
        raise RuntimeError("simulate transaction failure")

    with pytest.raises(RuntimeError, match="transaction failure"):
        store.run_guarded(cutover_id, digest, action)
    with psycopg.connect(isolated_dsn) as connection:
        row = connection.execute("SELECT count(*) FROM write_probe").fetchone()
        assert row is not None
        assert row[0] == 0


def test_cutover_activation_is_serialized(isolated_dsn: str) -> None:
    digest = _digest()
    store = PostgresCutoverStore(isolated_dsn, deployment_namespace="tenant-a")
    ids = [store.prepare(manifest_sha256=digest) for _ in range(2)]
    for identifier in ids:
        store.verify(identifier, manifest_sha256=digest)

    def activate(identifier: UUID) -> bool:
        try:
            store.activate(identifier, manifest_sha256=digest)
        except CutoverConflictError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(activate, ids))
    assert sorted(results) == [False, True]
