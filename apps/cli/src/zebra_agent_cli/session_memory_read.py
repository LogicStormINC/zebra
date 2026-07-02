from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.memories import MemoryQuery, MemoryStatus
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from zebra_agent_api.session_context import session_workspace_root


def read_session_memory(
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
    workspace_root = _session_workspace_root(
        SQLiteEventStore(database_path).list_for_session(session_key)
    )
    if workspace_root is None:
        return {
            "session_id": session_id,
            "database": str(database_path),
            "status": "memory_unavailable",
            "reason": "session workspace_root is unavailable",
        }
    records = SQLiteMemoryStore(database_path).list(
        MemoryQuery(
            repo_id=str(workspace_root),
            statuses=(
                MemoryStatus.CANDIDATE,
                MemoryStatus.CONFIRMED,
                MemoryStatus.SUPERSEDED,
                MemoryStatus.EXPIRED,
            ),
        )
    )
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace_root),
        "memories": [record.model_dump(mode="json") for record in records],
    }


def _session_workspace_root(events: Sequence[SessionEvent]) -> Path | None:
    return session_workspace_root(list(events))
