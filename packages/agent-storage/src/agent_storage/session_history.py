from __future__ import annotations

import json
from pathlib import Path
from sqlite3 import Row

from agent_core.domain.events import EventType
from agent_core.domain.session_history import (
    MAX_HISTORY_MESSAGE_CHARS,
    MAX_HISTORY_SNIPPET_CHARS,
    MAX_HISTORY_TITLE_CHARS,
    SessionHistoryMessage,
    SessionHistoryMode,
    SessionHistoryRequest,
    SessionHistoryResult,
    SessionHistorySummary,
)
from agent_core.domain.sessions import Session
from agent_core.ports.session_history import SessionHistoryPort

from agent_storage.database import SQLiteDatabase
from agent_storage.projections import SQLiteProjectionStore

MAX_SCANNED_SESSIONS = 100
MAX_SCANNED_MESSAGES = 2_000
SAFE_EVENT_TYPES = (
    EventType.USER_MESSAGE_RECEIVED.value,
    EventType.MODEL_RESPONSE_RECEIVED.value,
)


class SQLiteSessionHistory(SessionHistoryPort):
    def __init__(
        self,
        database_path: str | Path,
        *,
        allowed_session_ids: tuple[str, ...] | None = None,
    ) -> None:
        self._database = SQLiteDatabase(database_path)
        self._projections = SQLiteProjectionStore(database_path)
        self._allowed_session_ids = (
            frozenset(allowed_session_ids) if allowed_session_ids is not None else None
        )

    def scoped(
        self,
        allowed_session_ids: tuple[str, ...] | None,
    ) -> SessionHistoryPort:
        return SQLiteSessionHistory(
            self._database.database_path,
            allowed_session_ids=allowed_session_ids,
        )

    def query(self, request: SessionHistoryRequest) -> SessionHistoryResult:
        if request.mode is SessionHistoryMode.READ:
            return self._read(request)
        candidates = self._candidate_sessions(request.current_session_id)
        if request.mode is SessionHistoryMode.BROWSE:
            return self._browse(request, candidates)
        return self._search(request, candidates)

    def _candidate_sessions(self, current_session_id: str | None) -> list[Session]:
        sessions = self._projections.list_recent_sessions(limit=MAX_SCANNED_SESSIONS + 1)
        return [
            session
            for session in sessions
            if str(session.session_id) != current_session_id
            and (
                self._allowed_session_ids is None
                or str(session.session_id) in self._allowed_session_ids
            )
        ][:MAX_SCANNED_SESSIONS]

    def _browse(
        self, request: SessionHistoryRequest, candidates: list[Session]
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
        self, request: SessionHistoryRequest, candidates: list[Session]
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
                text = _safe_event_text(row)
                if text is not None and query in text.casefold():
                    message_matches += 1
                    if snippet is None:
                        snippet = _match_snippet(text, query)
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
            total = connection.execute(
                """
                SELECT COUNT(*) FROM session_events
                WHERE session_id = ? AND event_type IN (?, ?)
                """,
                (request.session_id, *SAFE_EVENT_TYPES),
            ).fetchone()[0]
            rows = connection.execute(
                """
                SELECT sequence, event_type, payload, created_at
                FROM session_events
                WHERE session_id = ? AND event_type IN (?, ?)
                ORDER BY sequence ASC
                LIMIT ? OFFSET ?
                """,
                (request.session_id, *SAFE_EVENT_TYPES, request.limit, request.offset),
            ).fetchall()
        messages = tuple(message for row in rows if (message := _message(row)) is not None)
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
        if (
            self._allowed_session_ids is not None
            and raw_session_id not in self._allowed_session_ids
        ):
            return None
        from uuid import UUID

        from agent_core.domain.identifiers import SessionId

        return self._projections.get_session(SessionId(UUID(raw_session_id)))

    def _safe_event_rows(self, session_id: str) -> list[Row]:
        with self._database.connect() as connection:
            return connection.execute(
                """
                SELECT sequence, event_type, payload, created_at
                FROM session_events
                WHERE session_id = ? AND event_type IN (?, ?)
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (session_id, *SAFE_EVENT_TYPES, MAX_SCANNED_MESSAGES),
            ).fetchall()

    def _first_user_preview(self, session: Session) -> str | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT sequence, event_type, payload, created_at
                FROM session_events
                WHERE session_id = ? AND event_type = ?
                ORDER BY sequence ASC
                LIMIT 1
                """,
                (str(session.session_id), EventType.USER_MESSAGE_RECEIVED.value),
            ).fetchone()
        text = _safe_event_text(row) if row is not None else None
        return _bounded(text, MAX_HISTORY_SNIPPET_CHARS) if text else None

    @staticmethod
    def _summary(
        session: Session, *, snippet: str | None = None, match_count: int = 0
    ) -> SessionHistorySummary:
        return SessionHistorySummary(
            session_id=str(session.session_id),
            title=_bounded(session.title, MAX_HISTORY_TITLE_CHARS),
            status=session.status.value,
            created_at=session.created_at,
            updated_at=session.updated_at,
            snippet=snippet,
            match_count=match_count,
        )


def _safe_event_text(row: Row) -> str | None:
    try:
        payload = json.loads(row["payload"])
    except (TypeError, json.JSONDecodeError):
        return None
    field = (
        "content"
        if row["event_type"] == EventType.USER_MESSAGE_RECEIVED.value
        else "assistant_message"
    )
    value = payload.get(field) if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def _message(row: Row) -> SessionHistoryMessage | None:
    text = _safe_event_text(row)
    if text is None:
        return None
    bounded = _bounded(text, MAX_HISTORY_MESSAGE_CHARS)
    from datetime import datetime

    return SessionHistoryMessage(
        sequence=row["sequence"],
        role=(
            "user" if row["event_type"] == EventType.USER_MESSAGE_RECEIVED.value else "assistant"
        ),
        content=bounded,
        created_at=datetime.fromisoformat(row["created_at"]),
        text_truncated=len(bounded) < len(text),
    )


def _match_snippet(text: str, query: str) -> str:
    position = text.casefold().find(query)
    start = max(0, position - 180)
    return _bounded(text[start : start + MAX_HISTORY_SNIPPET_CHARS], MAX_HISTORY_SNIPPET_CHARS)


def _bounded(value: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    return normalized[:maximum]
