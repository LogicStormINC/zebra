from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import (
    read_session_delivery_audit_records,
    serialize_session_delivery_audit_projection,
)

from zebra_agent_api.responses import ApiResponse


@dataclass(frozen=True)
class SessionDeliveryAuditApi:
    database_path: Path

    def get_delivery_audit(self, session_id: str) -> ApiResponse:
        session_key = SessionId(UUID(session_id))
        records = read_session_delivery_audit_records(self.database_path, session_key)
        if records is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        return ApiResponse(
            status_code=200,
            body=serialize_session_delivery_audit_projection(session_id, records),
        )
