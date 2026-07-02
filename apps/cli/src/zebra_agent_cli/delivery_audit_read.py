from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteDeliveryAuditStore, SQLiteProjectionStore


def read_delivery_audit(
    *,
    database_path: Path,
    session_id: str,
) -> dict[str, object]:
    session_key = SessionId(UUID(session_id))
    session = SQLiteProjectionStore(database_path).get_session(session_key)
    if session is None:
        return {
            "session_id": session_id,
            "database": str(database_path),
            "status": "not_found",
        }
    records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_key)
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "delivery_audit": [
            {
                "action": record.action,
                "status": record.status,
                "status_code": record.status_code,
                "policy_profile": record.policy_profile,
                "idempotency_key": record.idempotency_key,
                "result_metadata": record.result_metadata,
                "created_at": record.created_at.isoformat(),
            }
            for record in records
        ],
    }
