from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_storage.postgres import (
    CutoverConflictError,
    PostgresCutoverStore,
    SnapshotIntegrityError,
    apply_postgres_migrations,
    export_sqlite_snapshot,
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
