from __future__ import annotations

from pathlib import Path

from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.identifiers import SessionId

from agent_storage.delivery_audit import SQLiteDeliveryAuditStore
from agent_storage.projections import SQLiteProjectionStore


def read_session_delivery_audit_records(
    database_path: str | Path,
    session_id: SessionId,
) -> list[DeliveryAuditRecord] | None:
    if SQLiteProjectionStore(database_path).get_session(session_id) is None:
        return None
    return SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
