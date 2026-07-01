from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_runtime import WorkspaceDiffError, WorkspaceDiffService
from agent_storage import SQLiteEventStore, SQLiteProjectionStore


def read_session_diff(
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
            "status": "diff_unavailable",
            "reason": "session workspace_root is unavailable",
        }
    try:
        diff = WorkspaceDiffService().read_diff(workspace_root)
    except WorkspaceDiffError as error:
        return {
            "session_id": session_id,
            "database": str(database_path),
            "status": "diff_unavailable",
            "reason": str(error),
        }
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "workspace": str(diff.workspace_root),
        "clean": diff.clean,
        "git_status": diff.git_status,
        "diff": diff.diff,
    }


def _session_workspace_root(events: list[SessionEvent]) -> Path | None:
    workspace_root: Path | None = None
    for event in events:
        if event.event_type is not EventType.TASK_PREPARED:
            continue
        raw_workspace_root = event.payload.get("workspace_root")
        if isinstance(raw_workspace_root, str) and raw_workspace_root.strip():
            workspace_root = Path(raw_workspace_root).expanduser().resolve()
    return workspace_root
