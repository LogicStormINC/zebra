from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

MAX_HISTORY_QUERY_CHARS = 500
MAX_HISTORY_TITLE_CHARS = 200
MAX_HISTORY_SNIPPET_CHARS = 500
MAX_HISTORY_MESSAGE_CHARS = 1_000
MAX_HISTORY_SESSIONS = 10
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_SCOPE_SESSIONS = 20


def normalize_history_session_ids(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if len(values) > MAX_HISTORY_SCOPE_SESSIONS:
        raise ValueError(
            f"history_session_ids accepts at most {MAX_HISTORY_SCOPE_SESSIONS} sessions"
        )
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("history_session_ids must contain UUID strings")
        try:
            session_id = str(UUID(value.strip()))
        except (ValueError, AttributeError) as exc:
            raise ValueError("history_session_ids must contain UUID strings") from exc
        if session_id in normalized:
            raise ValueError("history_session_ids must not contain duplicates")
        normalized.append(session_id)
    return tuple(normalized)


class SessionHistoryMode(StrEnum):
    BROWSE = "browse"
    SEARCH = "search"
    READ = "read"


@dataclass(frozen=True)
class SessionHistoryRequest:
    mode: SessionHistoryMode
    query: str | None = None
    session_id: str | None = None
    offset: int = 0
    limit: int = 5
    current_session_id: str | None = None


@dataclass(frozen=True)
class SessionHistorySummary:
    session_id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    snippet: str | None = None
    match_count: int = 0


@dataclass(frozen=True)
class SessionHistoryMessage:
    sequence: int
    role: str
    content: str
    created_at: datetime
    text_truncated: bool = False


@dataclass(frozen=True)
class SessionHistoryResult:
    mode: SessionHistoryMode
    sessions: tuple[SessionHistorySummary, ...] = ()
    messages: tuple[SessionHistoryMessage, ...] = ()
    scanned_sessions: int = 0
    scanned_messages: int = 0
    offset: int = 0
    total_count: int = 0
    next_offset: int | None = None
    truncated: bool = False
