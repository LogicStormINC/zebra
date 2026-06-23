import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.identifiers import SessionId
from agent_core.ports.delivery_audit_store import DeliveryAuditStorePort

from agent_storage.database import SQLiteDatabase


class SQLiteDeliveryAuditStore(DeliveryAuditStorePort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def append(self, record: DeliveryAuditRecord) -> DeliveryAuditRecord:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO delivery_audit_records (
                    session_id,
                    action,
                    status,
                    status_code,
                    policy_profile,
                    idempotency_key,
                    result_metadata,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.session_id),
                    record.action,
                    record.status,
                    record.status_code,
                    record.policy_profile,
                    record.idempotency_key,
                    json.dumps(record.result_metadata, sort_keys=True),
                    record.created_at.isoformat(),
                ),
            )
        return record

    def list_for_session(self, session_id: SessionId) -> list[DeliveryAuditRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    session_id,
                    action,
                    status,
                    status_code,
                    policy_profile,
                    idempotency_key,
                    result_metadata,
                    created_at
                FROM delivery_audit_records
                WHERE session_id = ?
                ORDER BY rowid ASC
                """,
                (str(session_id),),
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_audit_records (
                    session_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    policy_profile TEXT,
                    idempotency_key TEXT,
                    result_metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_delivery_audit_session
                ON delivery_audit_records(session_id)
                """
            )


def _record_from_row(row: Any) -> DeliveryAuditRecord:
    metadata = json.loads(row["result_metadata"])
    if not isinstance(metadata, dict):
        raise ValueError("delivery audit metadata must be a JSON object")
    return DeliveryAuditRecord(
        session_id=SessionId(UUID(row["session_id"])),
        action=row["action"],
        status=row["status"],
        status_code=row["status_code"],
        policy_profile=row["policy_profile"],
        idempotency_key=row["idempotency_key"],
        result_metadata=dict(metadata),
        created_at=datetime.fromisoformat(row["created_at"]),
    )
