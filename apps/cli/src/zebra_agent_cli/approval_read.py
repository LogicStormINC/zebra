from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_storage import SQLiteProjectionStore
from agent_storage.database import SQLiteDatabase


def list_approvals(*, database_path: Path) -> dict[str, object]:
    approvals = [
        _approval_summary(session)
        for session in _list_waiting_sessions(database_path)
    ]
    return {
        "database": str(database_path),
        "approvals": approvals,
    }


def read_approval_detail(
    *,
    database_path: Path,
    approval_id: str,
) -> dict[str, object]:
    session = SQLiteProjectionStore(database_path).get_session(SessionId(UUID(approval_id)))
    if session is None:
        return {
            "approval_id": approval_id,
            "database": str(database_path),
            "status": "not_found",
        }
    return {
        "database": str(database_path),
        **_approval_summary(session),
    }


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


def _approval_summary(session: Session) -> dict[str, object]:
    body: dict[str, object] = {
        "approval_id": str(session.session_id),
        "session_id": str(session.session_id),
        "title": session.title,
        "status": session.status.value,
        "current_sequence": session.current_sequence,
    }
    approval_context = _serialize_approval_context(session.approval_context)
    if approval_context is not None:
        body["approval_context"] = approval_context
    return body


def _serialize_approval_context(context: ApprovalContext | None) -> dict[str, object] | None:
    if context is None:
        return None
    return context.to_mapping()
