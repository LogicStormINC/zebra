"""Source-bound user profile candidates and confirmed profile projection."""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent_core.application.memory_directives import safe_memory_text
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType

_TEMPORARY = re.compile(
    r"(?:这次|本次|这一轮|当前这轮|this time|for this (?:turn|request))",
    re.IGNORECASE,
)
_PROFILE_PATTERNS = (
    (
        "background",
        re.compile(
            r"^(?:我是|我的工作是|我的职责是|我负责|我主要负责)[：:，,\s]*(.+)$",
            re.IGNORECASE,
        ),
        "User background",
    ),
    (
        "goal",
        re.compile(r"^(?:我的长期目标是|我的目标是)[：:，,\s]*(.+)$", re.IGNORECASE),
        "User goal",
    ),
    (
        "background",
        re.compile(
            r"^(?:i am|i work as|i am responsible for)[,:\s]+(.+)$",
            re.IGNORECASE,
        ),
        "User background",
    ),
    (
        "goal",
        re.compile(r"^(?:my long-term goal is|my goal is)[,:\s]+(.+)$", re.IGNORECASE),
        "User goal",
    ),
)


@dataclass(frozen=True, slots=True)
class UserProfileCandidate:
    category: str
    text: str


@dataclass(frozen=True, slots=True)
class UserProfileItem:
    memory_id: str
    category: str
    text: str
    source_session_id: str | None
    updated_at: str


def user_profile_candidates(content: str) -> tuple[UserProfileCandidate, ...]:
    """Extract only explicit self-statements; inferred facts remain review candidates."""
    normalized = " ".join(content.strip().split())
    if not normalized or _TEMPORARY.search(normalized):
        return ()
    for category, pattern, label in _PROFILE_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is None:
            continue
        value = safe_memory_text(match.group(1))
        if value is None:
            return ()
        return (UserProfileCandidate(category, f"{label}: {value}"),)
    return ()


def confirmed_user_profile(records: tuple[MemoryRecord, ...]) -> tuple[UserProfileItem, ...]:
    """Project confirmed USER memories into a stable, source-visible profile."""
    items: list[UserProfileItem] = []
    for record in records:
        if record.status is not MemoryStatus.CONFIRMED:
            continue
        category, text = _profile_category(record)
        if category is None:
            continue
        items.append(
            UserProfileItem(
                memory_id=str(record.memory_id),
                category=category,
                text=text,
                source_session_id=(
                    None if record.source_session_id is None else str(record.source_session_id)
                ),
                updated_at=record.updated_at.isoformat(),
            )
        )
    return tuple(sorted(items, key=lambda item: (item.category, item.text, item.memory_id)))


def _profile_category(record: MemoryRecord) -> tuple[str | None, str]:
    if record.memory_type is MemoryType.PREFERENCE:
        return "preference", record.text
    for prefix, category in (
        ("User background: ", "background"),
        ("User goal: ", "goal"),
    ):
        if record.memory_type is MemoryType.EPISODIC and record.text.startswith(prefix):
            return category, record.text.removeprefix(prefix)
    return None, record.text
