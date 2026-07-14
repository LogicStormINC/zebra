from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_storage import SQLiteProjectionStore, SQLiteWorkspaceProjectionStore

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_summary import serialize_session_summary

DEFAULT_SESSION_LIMIT = 50
MAX_SESSION_LIMIT = 100


@dataclass(frozen=True)
class SessionListApi:
    database_path: Path

    def list_sessions(self, query: Mapping[str, str]) -> ApiResponse:
        limit = _parse_limit(query.get("limit"))
        if isinstance(limit, ApiResponse):
            return limit
        sessions = SQLiteProjectionStore(self.database_path).list_recent_sessions(limit=limit)
        workspace_store = SQLiteWorkspaceProjectionStore(self.database_path)
        # ponytail: bounded N+1 reads keep stores separate; use a join past MAX_SESSION_LIMIT.
        items = [
            serialize_session_summary(
                session,
                workspace_store.get_workspace(session.session_id),
                include_timestamps=True,
            )
            for session in sessions
        ]
        return ApiResponse(
            status_code=200,
            body={"sessions": items, "count": len(items), "limit": limit},
        )


def _parse_limit(raw: str | None) -> int | ApiResponse:
    if raw is None:
        return DEFAULT_SESSION_LIMIT
    try:
        limit = int(raw)
    except ValueError:
        limit = 0
    if 1 <= limit <= MAX_SESSION_LIMIT:
        return limit
    return ApiResponse(
        status_code=400,
        body={
            "status": "invalid_request",
            "reason": f"limit must be an integer between 1 and {MAX_SESSION_LIMIT}",
        },
    )
