from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

MAX_HISTORY_QUERY_CHARS = 500
MAX_HISTORY_TITLE_CHARS = 200
MAX_HISTORY_SNIPPET_CHARS = 500
MAX_HISTORY_MESSAGE_CHARS = 1_000
MAX_HISTORY_SESSIONS = 10
MAX_HISTORY_MESSAGES = 20


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
