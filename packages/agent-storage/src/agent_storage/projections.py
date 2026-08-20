import json
import sqlite3
from pathlib import Path

from agent_core.domain.clarifications import ClarificationContext
from agent_core.domain.goals import Goal
from agent_core.domain.identifiers import SessionId
from agent_core.domain.plans import SessionPlan
from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_core.ports.projection_store import ProjectionStorePort

from agent_storage.database import SQLiteDatabase, ensure_column


class SQLiteProjectionStore(ProjectionStorePort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def save_session(self, session: Session) -> Session:
        with self._database.connect() as connection:
            _save_session(connection, session)
        return session

    def get_session(self, session_id: SessionId) -> Session | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    session_id,
                    title,
                    status,
                    created_at,
                    updated_at,
                    current_sequence,
                    approval_context_json,
                    clarification_context_json,
                    task_plan_json,
                    goal_binding,
                    active_goal_json
                FROM session_projections
                WHERE session_id = ?
                """,
                (str(session_id),),
            ).fetchone()
        if row is None:
            return None
        return Session.model_validate(
            {
                "session_id": row["session_id"],
                "title": row["title"],
                "status": SessionStatus(row["status"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "current_sequence": row["current_sequence"],
                "approval_context": _approval_context_from_json(row["approval_context_json"]),
                "clarification_context": _clarification_context_from_json(
                    row["clarification_context_json"]
                ),
                "task_plan": _task_plan_from_json(row["task_plan_json"]),
                "goal_binding": row["goal_binding"],
                "active_goal": _active_goal_from_json(row["active_goal_json"]),
            }
        )

    def list_ready_sessions(self, *, limit: int) -> list[Session]:
        if limit <= 0:
            return []
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    session_id,
                    title,
                    status,
                    created_at,
                    updated_at,
                    current_sequence,
                    approval_context_json,
                    clarification_context_json,
                    task_plan_json,
                    goal_binding,
                    active_goal_json
                FROM session_projections
                WHERE status = ?
                ORDER BY updated_at ASC, created_at ASC, session_id ASC
                LIMIT ?
                """,
                (SessionStatus.READY.value, limit),
            ).fetchall()
        return [
            Session.model_validate(
                {
                    "session_id": row["session_id"],
                    "title": row["title"],
                    "status": SessionStatus(row["status"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "current_sequence": row["current_sequence"],
                    "approval_context": _approval_context_from_json(row["approval_context_json"]),
                    "clarification_context": _clarification_context_from_json(
                        row["clarification_context_json"]
                    ),
                    "task_plan": _task_plan_from_json(row["task_plan_json"]),
                    "goal_binding": row["goal_binding"],
                    "active_goal": _active_goal_from_json(row["active_goal_json"]),
                }
            )
            for row in rows
        ]

    def list_recent_sessions(self, *, limit: int) -> list[Session]:
        if limit <= 0:
            return []
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    session_id,
                    title,
                    status,
                    created_at,
                    updated_at,
                    current_sequence,
                    approval_context_json,
                    clarification_context_json,
                    task_plan_json,
                    goal_binding,
                    active_goal_json
                FROM session_projections
                ORDER BY updated_at DESC, created_at DESC, session_id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            Session.model_validate(
                {
                    "session_id": row["session_id"],
                    "title": row["title"],
                    "status": SessionStatus(row["status"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "current_sequence": row["current_sequence"],
                    "approval_context": _approval_context_from_json(row["approval_context_json"]),
                    "clarification_context": _clarification_context_from_json(
                        row["clarification_context_json"]
                    ),
                    "task_plan": _task_plan_from_json(row["task_plan_json"]),
                    "goal_binding": row["goal_binding"],
                    "active_goal": _active_goal_from_json(row["active_goal_json"]),
                }
            )
            for row in rows
        ]

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS session_projections (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    current_sequence INTEGER NOT NULL,
                    approval_context_json TEXT,
                    clarification_context_json TEXT,
                    task_plan_json TEXT,
                    goal_binding TEXT NOT NULL DEFAULT 'conversational',
                    active_goal_json TEXT
                )
                """
            )
            ensure_column(connection, "session_projections", "approval_context_json", "TEXT")
            ensure_column(connection, "session_projections", "clarification_context_json", "TEXT")
            ensure_column(connection, "session_projections", "task_plan_json", "TEXT")
            ensure_column(
                connection,
                "session_projections",
                "goal_binding",
                "TEXT NOT NULL DEFAULT 'conversational'",
            )
            ensure_column(connection, "session_projections", "active_goal_json", "TEXT")


def _approval_context_json(context: ApprovalContext | None) -> str | None:
    if context is None:
        return None
    return json.dumps(context.model_dump(mode="json"))


def _save_session(connection: sqlite3.Connection, session: Session) -> None:
    connection.execute(
        """
        INSERT INTO session_projections (
            session_id,
            title,
            status,
            created_at,
            updated_at,
            current_sequence,
            approval_context_json,
            clarification_context_json,
            task_plan_json,
            goal_binding,
            active_goal_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            title = excluded.title,
            status = excluded.status,
            created_at = excluded.created_at,
            updated_at = excluded.updated_at,
            current_sequence = excluded.current_sequence,
            approval_context_json = excluded.approval_context_json,
            clarification_context_json = excluded.clarification_context_json,
            task_plan_json = excluded.task_plan_json,
            goal_binding = excluded.goal_binding,
            active_goal_json = excluded.active_goal_json
        """,
        (
            str(session.session_id),
            session.title,
            session.status.value,
            session.created_at.isoformat(),
            session.updated_at.isoformat(),
            session.current_sequence,
            _approval_context_json(session.approval_context),
            _clarification_context_json(session.clarification_context),
            _task_plan_json(session.task_plan),
            session.goal_binding.value,
            _active_goal_json(session),
        ),
    )


def _approval_context_from_json(value: object) -> ApprovalContext | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return ApprovalContext.model_validate(json.loads(value))


def _clarification_context_json(context: ClarificationContext | None) -> str | None:
    if context is None:
        return None
    return json.dumps(context.model_dump(mode="json"))


def _clarification_context_from_json(value: object) -> ClarificationContext | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return ClarificationContext.model_validate(json.loads(value))


def _task_plan_json(plan: SessionPlan) -> str:
    return json.dumps(plan.model_dump(mode="json"))


def _task_plan_from_json(value: object) -> SessionPlan:
    if not isinstance(value, str) or not value.strip():
        return SessionPlan()
    return SessionPlan.model_validate(json.loads(value))


def _active_goal_json(session: Session) -> str | None:
    if session.active_goal is None:
        return None
    return json.dumps(session.active_goal.model_dump(mode="json"))


def _active_goal_from_json(value: object) -> Goal | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Goal.model_validate(json.loads(value))
