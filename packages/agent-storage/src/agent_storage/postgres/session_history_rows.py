from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from agent_core.domain.events import EventType
from agent_core.domain.session_history import (
    MAX_HISTORY_MESSAGE_CHARS,
    MAX_HISTORY_SNIPPET_CHARS,
    SessionHistoryMessage,
)
from agent_core.domain.sessions import Session


def session_from_row(row: Mapping[str, Any]) -> Session:
    values = dict(row)
    values["approval_context"] = values.pop("approval_context_json")
    values["clarification_context"] = values.pop("clarification_context_json")
    values["task_plan"] = values.pop("task_plan_json")
    return Session.model_validate(values)


def safe_event_text(row: Mapping[str, Any]) -> str | None:
    payload = row.get("payload")
    if not isinstance(payload, Mapping):
        return None
    field = (
        "content"
        if row.get("event_type") == EventType.USER_MESSAGE_RECEIVED.value
        else "assistant_message"
    )
    value = payload.get(field)
    return value if isinstance(value, str) and value.strip() else None


def message_from_row(row: Mapping[str, Any]) -> SessionHistoryMessage | None:
    text = safe_event_text(row)
    if text is None:
        return None
    bounded = bounded_text(text, MAX_HISTORY_MESSAGE_CHARS)
    created_at = row["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    return SessionHistoryMessage(
        sequence=row["sequence"],
        role=(
            "user" if row["event_type"] == EventType.USER_MESSAGE_RECEIVED.value else "assistant"
        ),
        content=bounded,
        created_at=created_at,
        text_truncated=len(bounded) < len(text),
    )


def match_snippet(text: str, query: str) -> str:
    position = text.casefold().find(query)
    start = max(0, position - 180)
    return bounded_text(text[start : start + MAX_HISTORY_SNIPPET_CHARS], MAX_HISTORY_SNIPPET_CHARS)


def bounded_text(value: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    return normalized[:maximum]
