from datetime import datetime
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.ports.model_call_store import ModelCallStorePort

from agent_storage.database import SQLiteDatabase, ensure_column


class SQLiteModelCallStore(ModelCallStorePort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def upsert(self, record: ModelCallRecord) -> ModelCallRecord:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO model_calls (
                    session_id,
                    sequence,
                    provider,
                    model_name,
                    input_tokens,
                    estimated_input_tokens,
                    input_token_limit,
                    input_token_estimate_error,
                    output_tokens,
                    total_tokens,
                    latency_ms,
                    cache_hit,
                    cost_usd,
                    assistant_message,
                    tool_call_count,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, sequence) DO UPDATE SET
                    provider = excluded.provider,
                    model_name = excluded.model_name,
                    input_tokens = excluded.input_tokens,
                    estimated_input_tokens = excluded.estimated_input_tokens,
                    input_token_limit = excluded.input_token_limit,
                    input_token_estimate_error = excluded.input_token_estimate_error,
                    output_tokens = excluded.output_tokens,
                    total_tokens = excluded.total_tokens,
                    latency_ms = excluded.latency_ms,
                    cache_hit = excluded.cache_hit,
                    cost_usd = excluded.cost_usd,
                    assistant_message = excluded.assistant_message,
                    tool_call_count = excluded.tool_call_count,
                    created_at = excluded.created_at
                """,
                (
                    str(record.session_id),
                    record.sequence,
                    record.provider,
                    record.model_name,
                    record.input_tokens,
                    record.estimated_input_tokens,
                    record.input_token_limit,
                    record.input_token_estimate_error,
                    record.output_tokens,
                    record.total_tokens,
                    record.latency_ms,
                    None if record.cache_hit is None else int(record.cache_hit),
                    record.cost_usd,
                    record.assistant_message,
                    record.tool_call_count,
                    record.created_at.isoformat(),
                ),
            )
        return record

    def list_for_session(self, session_id: SessionId) -> list[ModelCallRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    session_id,
                    sequence,
                    provider,
                    model_name,
                    input_tokens,
                    estimated_input_tokens,
                    input_token_limit,
                    input_token_estimate_error,
                    output_tokens,
                    total_tokens,
                    latency_ms,
                    cache_hit,
                    cost_usd,
                    assistant_message,
                    tool_call_count,
                    created_at
                FROM model_calls
                WHERE session_id = ?
                ORDER BY sequence ASC
                """,
                (str(session_id),),
            ).fetchall()
        return [
            ModelCallRecord(
                session_id=SessionId(UUID(row["session_id"])),
                sequence=row["sequence"],
                provider=row["provider"],
                model_name=row["model_name"],
                input_tokens=row["input_tokens"],
                estimated_input_tokens=row["estimated_input_tokens"],
                input_token_limit=row["input_token_limit"],
                input_token_estimate_error=row["input_token_estimate_error"],
                output_tokens=row["output_tokens"],
                total_tokens=row["total_tokens"],
                latency_ms=row["latency_ms"],
                cache_hit=None if row["cache_hit"] is None else bool(row["cache_hit"]),
                cost_usd=row["cost_usd"],
                assistant_message=row["assistant_message"],
                tool_call_count=row["tool_call_count"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS model_calls (
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    provider TEXT,
                    model_name TEXT,
                    input_tokens INTEGER,
                    estimated_input_tokens INTEGER,
                    input_token_limit INTEGER,
                    input_token_estimate_error INTEGER,
                    output_tokens INTEGER,
                    total_tokens INTEGER,
                    latency_ms INTEGER,
                    cache_hit INTEGER,
                    cost_usd REAL,
                    assistant_message TEXT NOT NULL,
                    tool_call_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, sequence)
                )
                """
            )
            for name in (
                "estimated_input_tokens",
                "input_token_limit",
                "input_token_estimate_error",
            ):
                ensure_column(connection, "model_calls", name, "INTEGER")
