import sqlite3
from pathlib import Path


class SQLiteDatabase:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def database_path(self) -> Path:
        return self._database_path

    def connect(self) -> sqlite3.Connection:
        # Long tasks write heavily (events, effect ledger, projections) from
        # concurrent threads; the default rollback journal plus the 5s busy
        # timeout surfaced as "database is locked" mid-run. WAL lets readers
        # proceed during writes and a 30s busy timeout absorbs writer bursts.
        connection = sqlite3.connect(self._database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection


def ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    """Add ``table.column`` if absent, tolerating the concurrent-migration race.

    SQLite has no ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``, so migrations do a
    ``PRAGMA table_info`` check then ``ALTER``. Under concurrent construction
    (e.g. the API serving parallel requests), two connections can both see the
    column as absent and both try to add it; the loser raises
    ``duplicate column name``. This helper makes the add idempotent across
    connections by swallowing that specific error (the desired state — column
    present — already holds).
    """
    existing = {
        row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column in existing:
        return
    try:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc):
            raise
