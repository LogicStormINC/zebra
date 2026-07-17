from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId


def parse_session_id(
    session_id: str,
    *,
    database_path: Path,
) -> SessionId | dict[str, object]:
    try:
        return SessionId(UUID(session_id))
    except ValueError:
        return {
            "session_id": session_id,
            "database": str(database_path),
            "status": "invalid_request",
            "reason": "session_id must be a valid UUID",
        }
