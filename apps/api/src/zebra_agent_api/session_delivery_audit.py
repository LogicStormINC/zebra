from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import ControlPlaneStores, SQLiteDeliveryAuditStore

from zebra_agent_api.responses import ApiResponse


@dataclass(frozen=True)
class SessionDeliveryAuditApi:
    database_path: Path
    stores: ControlPlaneStores

    def get_delivery_audit(self, session_id: str) -> ApiResponse:
        session_key = SessionId(UUID(session_id))
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        records = SQLiteDeliveryAuditStore(self.database_path).list_for_session(session_key)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
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
            },
        )
