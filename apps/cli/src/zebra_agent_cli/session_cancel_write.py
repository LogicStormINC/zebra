from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from zebra_agent_worker import SessionControlError, SessionControlService


def cancel_session(
    *,
    database_path: Path,
    session_id: str,
) -> dict[str, object]:
    try:
        result = SessionControlService(database_path).cancel_session(
            SessionId(UUID(session_id))
        )
    except SessionControlError as error:
        reason = str(error)
        if reason == "session was not found":
            return {
                "session_id": session_id,
                "database": str(database_path),
                "status": "not_found",
            }
        return {
            "session_id": session_id,
            "database": str(database_path),
            "status": "not_cancellable",
            "reason": reason.replace(" ", "_"),
        }
    return {
        "session_id": session_id,
        "database": str(database_path),
        "cancelled": True,
        "status": "cancelled",
        "workspace_status": result.workspace.status.value,
    }
