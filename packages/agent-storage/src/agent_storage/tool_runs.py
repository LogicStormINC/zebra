from datetime import datetime
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports.tool_run_store import ToolRunStorePort

from agent_storage.database import SQLiteDatabase


class SQLiteToolRunStore(ToolRunStorePort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def upsert(self, record: ToolRunRecord) -> ToolRunRecord:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_runs (
                    session_id,
                    sequence,
                    tool_name,
                    status,
                    idempotency_key,
                    output,
                    artifact_uri,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, sequence) DO UPDATE SET
                    tool_name = excluded.tool_name,
                    status = excluded.status,
                    idempotency_key = excluded.idempotency_key,
                    output = excluded.output,
                    artifact_uri = excluded.artifact_uri,
                    created_at = excluded.created_at
                """,
                (
                    str(record.session_id),
                    record.sequence,
                    record.tool_name,
                    record.status,
                    record.idempotency_key,
                    record.output,
                    record.artifact_uri,
                    record.created_at.isoformat(),
                ),
            )
        return record

    def list_for_session(self, session_id: SessionId) -> list[ToolRunRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    session_id,
                    sequence,
                    tool_name,
                    status,
                    idempotency_key,
                    output,
                    artifact_uri,
                    created_at
                FROM tool_runs
                WHERE session_id = ?
                ORDER BY sequence ASC
                """,
                (str(session_id),),
            ).fetchall()
        return [
            ToolRunRecord(
                session_id=SessionId(UUID(row["session_id"])),
                sequence=row["sequence"],
                tool_name=row["tool_name"],
                status=row["status"],
                idempotency_key=row["idempotency_key"],
                output=row["output"],
                artifact_uri=row["artifact_uri"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_runs (
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    tool_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    idempotency_key TEXT,
                    output TEXT NOT NULL,
                    artifact_uri TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, sequence)
                )
                """
            )
