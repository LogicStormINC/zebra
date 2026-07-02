from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from zebra_agent_worker import SessionControlError, SessionControlService


def suspend_session(
    *,
    database_path: Path,
    session_id: str,
) -> dict[str, object]:
    try:
        result = SessionControlService(database_path).suspend_session(
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
            "status": "not_suspendable",
            "reason": reason.replace(" ", "_"),
        }
    return {
        "session_id": session_id,
        "database": str(database_path),
        "suspended": True,
        "status": "suspended",
        "workspace_status": result.workspace.status.value,
        "snapshot_id": result.workspace.snapshot_id,
    }
