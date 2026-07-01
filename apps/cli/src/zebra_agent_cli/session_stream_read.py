from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore


def read_session_stream(
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
    events = SQLiteEventStore(database_path).list_for_session(session_key)
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "events": [
            {
                "event_id": str(event.event_id),
                "sequence": event.sequence,
                "event_type": event.event_type.value,
                "actor": event.actor.value,
                "created_at": event.created_at.isoformat(),
                "payload": event.payload,
            }
            for event in events
        ],
    }
