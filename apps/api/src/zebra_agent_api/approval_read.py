from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SQLiteAgentTaskStore, SQLiteProjectionStore
from agent_storage.database import SQLiteDatabase

from zebra_agent_api.approval_context import serialize_approval_context
from zebra_agent_api.responses import ApiResponse


@dataclass(frozen=True)
class ApprovalReadApi:
    database_path: Path

    def list_approvals(self) -> ApiResponse:
        task_store = SQLiteAgentTaskStore(self.database_path)
        return ApiResponse(
            status_code=200,
            body={
                "approvals": [
                    _approval_summary(
                        session,
                        task_id=str(task_store.ensure_for_session(session.session_id).task_id),
                    )
                    for session in _list_waiting_sessions(self.database_path)
                ]
            },
        )

    def get_approval(self, approval_id: str) -> ApiResponse:
        session = SQLiteProjectionStore(self.database_path).get_session(
            SessionId(UUID(approval_id))
        )
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"approval_id": approval_id, "status": "not_found"},
            )
        task_id = str(
            SQLiteAgentTaskStore(self.database_path).ensure_for_session(session.session_id).task_id
        )
        return ApiResponse(status_code=200, body=_approval_summary(session, task_id=task_id))


def _list_waiting_sessions(database_path: Path) -> list[Session]:
    database = SQLiteDatabase(database_path)
    store = SQLiteProjectionStore(database_path)
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT session_id
            FROM session_projections
            WHERE status = ?
            ORDER BY updated_at ASC, created_at ASC, session_id ASC
            """,
            (SessionStatus.WAITING_APPROVAL.value,),
        ).fetchall()
    sessions: list[Session] = []
    for row in rows:
        session = store.get_session(SessionId(UUID(row["session_id"])))
        if session is not None:
            sessions.append(session)
    return sessions


def _approval_summary(session: Session, *, task_id: str) -> dict[str, object]:
    body: dict[str, object] = {
        "approval_id": str(session.session_id),
        "session_id": task_id,
        "title": session.title,
        "status": session.status.value,
        "current_sequence": session.current_sequence,
    }
    approval_context = serialize_approval_context(session.approval_context)
    if approval_context is not None:
        body["approval_context"] = approval_context
    return body
