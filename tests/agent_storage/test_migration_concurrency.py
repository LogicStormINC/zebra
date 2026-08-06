from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from agent_storage import SQLiteProjectionStore, SQLiteWorkspaceProjectionStore
from agent_storage.database import SQLiteDatabase, ensure_column


def test_ensure_column_is_idempotent(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "x.sqlite")
    with database.connect() as connection:
        connection.execute("CREATE TABLE demo (a TEXT)")
    with database.connect() as connection:
        ensure_column(connection, "demo", "b", "TEXT")
    # A second pass sees the column already present and is a no-op.
    with database.connect() as connection:
        ensure_column(connection, "demo", "b", "TEXT")
    columns = {
        row[1] for row in sqlite3.connect(tmp_path / "x.sqlite").execute("PRAGMA table_info(demo)")
    }
    assert {"a", "b"} <= columns


def test_database_connections_use_wal_and_long_busy_timeout(
    tmp_path: Path,
) -> None:
    """Long tasks write heavily from concurrent threads; connections must run
    in WAL mode with a generous busy timeout instead of the default 5s
    rollback-journal lock window."""
    database = SQLiteDatabase(tmp_path / "wal.sqlite")
    with database.connect() as connection:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]
    assert str(mode).lower() == "wal"
    assert int(busy_timeout) >= 30000
    assert int(synchronous) == 1


def test_concurrent_ensure_column_does_not_raise(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "race.sqlite")
    with database.connect() as connection:
        connection.execute("CREATE TABLE demo (a TEXT)")

    errors: list[BaseException] = []
    barrier = threading.Barrier(20)

    def add_repeatedly() -> None:
        barrier.wait()
        try:
            for _ in range(10):
                with database.connect() as connection:
                    ensure_column(connection, "demo", "added", "TEXT")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=add_repeatedly) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors


def test_projection_store_init_is_concurrency_safe(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    errors: list[BaseException] = []
    barrier = threading.Barrier(16)

    def construct() -> None:
        barrier.wait()
        try:
            for _ in range(4):
                SQLiteProjectionStore(database)
                SQLiteWorkspaceProjectionStore(database)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=construct) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    columns = {
        row[1]
        for row in sqlite3.connect(database)
        .execute("PRAGMA table_info(session_projections)")
        .fetchall()
    }
    assert "clarification_context_json" in columns
