from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.application import (
    SessionMessageAppendCommand,
    SessionMessageAppendService,
    project_turns,
)
from agent_core.application.session_projection import apply_event
from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore


def append_session_message(
    *,
    database_path: Path,
    session_id: str,
    content: str,
    clarification_id: str | None = None,
) -> dict[str, object]:
    if not content.strip():
        return {
            "database": str(database_path),
            "status": "invalid_request",
            "reason": "content must be a non-blank string",
        }
    projection_store = SQLiteProjectionStore(database_path)
    session = projection_store.get_session(SessionId(UUID(session_id)))
    if session is None:
        return {
            "session_id": session_id,
            "database": str(database_path),
            "status": "not_found",
        }
    try:
        event = SessionMessageAppendService().build_event(
            session=session,
            next_sequence=session.current_sequence + 1,
            command=SessionMessageAppendCommand(
                content=content.strip(),
                clarification_id=clarification_id,
                prior_human_turns=len(
                    project_turns(SQLiteEventStore(database_path).list_for_session(session.session_id))
                ),
            ),
        )
    except ValueError as exc:
        return {
            "session_id": session_id,
            "database": str(database_path),
            "status": "not_appendable",
            "reason": (
                "cannot_append_to_terminal_session"
                if "terminal session" in str(exc)
                else str(exc)
            ),
        }
    SQLiteEventStore(database_path).append(event)
    updated_session = projection_store.save_session(apply_event(session, event))
    return {
        "session_id": session_id,
        "database": str(database_path),
        "appended": True,
        **(
            {"clarification_resolved": True, "clarification_id": clarification_id}
            if event.event_type.value == "clarification_responded"
            else {}
        ),
        "content": content.strip(),
        "sequence": event.sequence,
        "status": updated_session.status.value,
        "current_sequence": updated_session.current_sequence,
    }
