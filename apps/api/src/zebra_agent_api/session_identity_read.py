from __future__ import annotations

from uuid import UUID

from agent_core.domain.identifiers import SessionId

from zebra_agent_api.responses import ApiResponse


def _parse_session_id(session_id: str) -> SessionId | ApiResponse:
    try:
        return SessionId(UUID(session_id))
    except ValueError:
        return ApiResponse(
            status_code=400,
            body={
                "session_id": session_id,
                "status": "invalid_request",
                "reason": "session_id must be a valid UUID",
            },
        )
