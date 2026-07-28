from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agent_core.ports.idempotency_store import IdempotencyRecord, IdempotencyStorePort

from agent_storage.database import SQLiteDatabase


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused with a different request."""


class SQLiteIdempotencyStore(IdempotencyStorePort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def get(self, *, action: str, idempotency_key: str) -> IdempotencyRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    action,
                    idempotency_key,
                    request_hash,
                    status_code,
                    response_body,
                    created_at
                FROM idempotency_records
                WHERE action = ? AND idempotency_key = ?
                """,
                (action, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        return IdempotencyRecord(
            action=row["action"],
            idempotency_key=row["idempotency_key"],
            request_hash=row["request_hash"],
            status_code=row["status_code"],
            response_body=json.loads(row["response_body"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save(self, record: IdempotencyRecord) -> IdempotencyRecord:
        existing = self.get(
            action=record.action,
            idempotency_key=record.idempotency_key,
        )
        if existing is not None:
            if existing.request_hash != record.request_hash:
                raise IdempotencyConflictError("idempotency key reused with different request")
            return existing
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO idempotency_records (
                    action,
                    idempotency_key,
                    request_hash,
                    status_code,
                    response_body,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.action,
                    record.idempotency_key,
                    record.request_hash,
                    record.status_code,
                    json.dumps(record.response_body, sort_keys=True),
                    record.created_at.isoformat(),
                ),
            )
        return record

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    action TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    response_body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (action, idempotency_key)
                )
                """
            )


def new_idempotency_record(
    *,
    action: str,
    idempotency_key: str,
    request_hash: str,
    status_code: int,
    response_body: dict[str, object],
) -> IdempotencyRecord:
    return IdempotencyRecord(
        action=action,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        status_code=status_code,
        response_body=response_body,
        created_at=datetime.now(UTC),
    )
