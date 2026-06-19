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
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
