from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_config import ZebraAgentSettings, load_settings


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

    def get_session_stream(self, session_id: str) -> ApiResponse:
        session_key = SessionId(UUID(session_id))
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={
                    "session_id": session_id,
                    "status": "not_found",
                },
            )
        events = SQLiteEventStore(self.database_path).list_for_session(session_key)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
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
            },
        )


def create_app(
    database_path: str | Path | None = None,
    *,
    settings: ZebraAgentSettings | None = None,
) -> ZebraAgentApi:
    active_settings = settings or load_settings()
    return ZebraAgentApi(database_path=Path(database_path or active_settings.database_url))
