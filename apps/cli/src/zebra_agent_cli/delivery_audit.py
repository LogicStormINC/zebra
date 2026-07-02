from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import (
    read_session_delivery_audit_records,
    serialize_session_delivery_audit_projection,
)


def read_delivery_audit(
    *,
    database_path: Path,
    session_id: str,
) -> dict[str, object]:
    session_key = SessionId(UUID(session_id))
    records = read_session_delivery_audit_records(database_path, session_key)
    if records is None:
        return {
            "session_id": session_id,
            "database": str(database_path),
            "status": "not_found",
        }
    return {
        "database": str(database_path),
        **serialize_session_delivery_audit_projection(session_id, records),
    }
