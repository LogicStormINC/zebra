from __future__ import annotations

from typing import Any
from uuid import UUID

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventType
from agent_core.domain.session_history import (
    MAX_HISTORY_SNIPPET_CHARS,
    MAX_HISTORY_TITLE_CHARS,
    SessionHistoryMode,
    SessionHistoryRequest,
    SessionHistoryResult,
    SessionHistorySummary,
)
from agent_core.domain.sessions import Session
from agent_core.ports.session_history import SessionHistoryPort

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.session_history_rows import (
    bounded_text,
    match_snippet,
    message_from_row,
    safe_event_text,
    session_from_row,
)

MAX_SCANNED_SESSIONS = 100
MAX_SCANNED_MESSAGES = 2_000
SAFE_EVENT_TYPES = (
    EventType.USER_MESSAGE_RECEIVED.value,
    EventType.MODEL_RESPONSE_RECEIVED.value,
)


class PostgresSessionHistory(SessionHistoryPort):
    """Namespace-scoped, read-only Session History composition."""

    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        scope: OpaqueAuthorityScope,
    ) -> None:
        self._dsn = dsn
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._scope = scope

    def scoped(
        self,
        allowed_session_ids: tuple[str, ...] | None,
    ) -> SessionHistoryPort:
        return PostgresSessionHistory(
            self._dsn,
            deployment_namespace=self._database.deployment_namespace,
            scope=OpaqueAuthorityScope(
                authority_issuer=self._scope.authority_issuer,
                namespace_id=self._scope.namespace_id,
                allowed_session_ids=allowed_session_ids,
            ),
        )

    def query(self, request: SessionHistoryRequest) -> SessionHistoryResult:
        if request.mode is SessionHistoryMode.READ:
            return self._read(request)
        candidates = self._candidate_sessions(request.current_session_id)
        if request.mode is SessionHistoryMode.BROWSE:
            return self._browse(request, candidates)
        return self._search(request, candidates)

    def _candidate_sessions(self, current_session_id: str | None) -> list[Session]:
        if self._scope.is_deny_all:
            return []
        clause, values = self._scope_clause()
        current_clause = " AND session_id <> %s" if current_session_id is not None else ""
        current_values = (current_session_id,) if current_session_id is not None else ()
        query = f"""
            SELECT session_id, title, status, created_at, updated_at, current_sequence,
                   approval_context_json, clarification_context_json, task_plan_json
            FROM session_projections
            WHERE deployment_namespace = %s{clause}{current_clause}
            ORDER BY updated_at DESC, created_at DESC, session_id ASC
            LIMIT %s
        """
        with self._database.connect() as connection:
            rows = connection.execute(
                query,
                (
                    self._database.deployment_namespace,
                    *values,
                    *current_values,
                    MAX_SCANNED_SESSIONS + 1,
                ),
            ).fetchall()
        return [session_from_row(row) for row in rows[:MAX_SCANNED_SESSIONS]]

    def _browse(
        self,
        request: SessionHistoryRequest,
        candidates: list[Session],
    ) -> SessionHistoryResult:
        summaries = tuple(
            self._summary(session, snippet=self._first_user_preview(session))
            for session in candidates[: request.limit]
        )
        return SessionHistoryResult(
            mode=request.mode,
            sessions=summaries,
            scanned_sessions=min(len(candidates), request.limit),
            truncated=len(candidates) > request.limit,
        )

    def _search(
        self,
        request: SessionHistoryRequest,
        candidates: list[Session],
    ) -> SessionHistoryResult:
        query = (request.query or "").casefold()
        matches: list[tuple[int, int, Session, str | None]] = []
        scanned_messages = 0
        scan_truncated = False
        for session in candidates:
            title_match = int(query in session.title.casefold())
            message_matches = 0
            snippet: str | None = None
            for row in self._safe_event_rows(str(session.session_id)):
                if scanned_messages >= MAX_SCANNED_MESSAGES:
                    scan_truncated = True
                    break
                scanned_messages += 1
                text = safe_event_text(row)
                if text is not None and query in text.casefold():
                    message_matches += 1
                    if snippet is None:
                        snippet = match_snippet(text, query)
            if title_match or message_matches:
                matches.append((title_match, message_matches, session, snippet))
            if scan_truncated:
                break
        matches.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                -item[2].updated_at.timestamp(),
                str(item[2].session_id),
            )
        )
        page = matches[: request.limit]
        return SessionHistoryResult(
            mode=request.mode,
            sessions=tuple(
                self._summary(session, snippet=snippet, match_count=title + count)
                for title, count, session, snippet in page
            ),
            scanned_sessions=min(len(candidates), MAX_SCANNED_SESSIONS),
            scanned_messages=scanned_messages,
            truncated=scan_truncated or len(matches) > request.limit,
        )

    def _read(self, request: SessionHistoryRequest) -> SessionHistoryResult:
        assert request.session_id is not None
        if request.session_id == request.current_session_id:
            return SessionHistoryResult(mode=request.mode, offset=request.offset)
        session = self._session(request.session_id)
        if session is None:
            return SessionHistoryResult(mode=request.mode, offset=request.offset)
        with self._database.connect() as connection:
            total_row = connection.execute(
                """
                SELECT COUNT(*)
                FROM session_events
                WHERE deployment_namespace = %s AND session_id = %s
                  AND event_type IN (%s, %s)
                """,
                (
                    self._database.deployment_namespace,
                    session.session_id,
                    *SAFE_EVENT_TYPES,
                ),
            ).fetchone()
            assert total_row is not None
            total = int(total_row["count"])
            rows = connection.execute(
                """
                SELECT sequence, event_type, payload, created_at
                FROM session_events
                WHERE deployment_namespace = %s AND session_id = %s
                  AND event_type IN (%s, %s)
                ORDER BY sequence ASC
                LIMIT %s OFFSET %s
                """,
                (
                    self._database.deployment_namespace,
                    session.session_id,
                    *SAFE_EVENT_TYPES,
                    request.limit,
                    request.offset,
                ),
            ).fetchall()
        messages = tuple(message for row in rows if (message := message_from_row(row)) is not None)
        next_offset = request.offset + len(rows) if request.offset + len(rows) < total else None
        return SessionHistoryResult(
            mode=request.mode,
            sessions=(self._summary(session),),
            messages=messages,
            scanned_sessions=1,
            scanned_messages=len(rows),
            offset=request.offset,
            total_count=total,
            next_offset=next_offset,
            truncated=next_offset is not None,
        )

    def _session(self, raw_session_id: str) -> Session | None:
        try:
            session_id = UUID(raw_session_id)
        except (AttributeError, ValueError):
            return None
        if not self._scope.allows_session(session_id):
            return None
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT session_id, title, status, created_at, updated_at, current_sequence,
                       approval_context_json, clarification_context_json, task_plan_json
                FROM session_projections
                WHERE deployment_namespace = %s AND session_id = %s
                """,
                (self._database.deployment_namespace, session_id),
            ).fetchone()
        return session_from_row(row) if row is not None else None

    def _safe_event_rows(self, session_id: str) -> list[dict[str, Any]]:
        with self._database.connect() as connection:
            return connection.execute(
                """
                SELECT sequence, event_type, payload, created_at
                FROM session_events
                WHERE deployment_namespace = %s AND session_id = %s
                  AND event_type IN (%s, %s)
                ORDER BY sequence ASC
                LIMIT %s
                """,
                (
                    self._database.deployment_namespace,
                    UUID(session_id),
                    *SAFE_EVENT_TYPES,
                    MAX_SCANNED_MESSAGES,
                ),
            ).fetchall()

    def _first_user_preview(self, session: Session) -> str | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT event_type, payload
                FROM session_events
                WHERE deployment_namespace = %s AND session_id = %s
                  AND event_type = %s
                ORDER BY sequence ASC
                LIMIT 1
                """,
                (
                    self._database.deployment_namespace,
                    session.session_id,
                    EventType.USER_MESSAGE_RECEIVED.value,
                ),
            ).fetchone()
        text = safe_event_text(row) if row is not None else None
        return bounded_text(text, MAX_HISTORY_SNIPPET_CHARS) if text else None

    def _scope_clause(self) -> tuple[str, tuple[object, ...]]:
        allowed = self._scope.allowed_session_ids
        if allowed is None:
            return "", ()
        if not allowed:
            return " AND FALSE", ()
        return " AND session_id = ANY(%s)", ([UUID(session_id) for session_id in allowed],)

    @staticmethod
    def _summary(
        session: Session,
        *,
        snippet: str | None = None,
        match_count: int = 0,
    ) -> SessionHistorySummary:
        return SessionHistorySummary(
            session_id=str(session.session_id),
            title=bounded_text(session.title, MAX_HISTORY_TITLE_CHARS),
            status=session.status.value,
            created_at=session.created_at,
            updated_at=session.updated_at,
            snippet=snippet,
            match_count=match_count,
        )
