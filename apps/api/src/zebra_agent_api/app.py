from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteProjectionStore


@dataclass(frozen=True)
class ApiResponse:
    status_code: int
    body: dict[str, object]


@dataclass(frozen=True)
class ZebraAgentApi:
    database_path: Path

    def health(self) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "status": "ok",
                "service": "zebra-agent-api",
            },
        )

    def get_session(self, session_id: str) -> ApiResponse:
        session = SQLiteProjectionStore(self.database_path).get_session(
            SessionId(UUID(session_id))
        )
        if session is None:
            return ApiResponse(
                status_code=404,
                body={
                    "session_id": session_id,
                    "status": "not_found",
                },
            )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": str(session.session_id),
                "title": session.title,
                "status": session.status.value,
                "current_sequence": session.current_sequence,
            },
        )


def create_app(database_path: str | Path = ".zebra-agent/sessions.sqlite") -> ZebraAgentApi:
    return ZebraAgentApi(database_path=Path(database_path))
