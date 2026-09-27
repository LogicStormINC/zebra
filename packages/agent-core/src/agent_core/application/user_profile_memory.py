"""Source-bound user profile candidates and confirmed profile projection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from agent_core.application.memory_directives import safe_memory_text
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType

_TEMPORARY = re.compile(
    r"(?:这次|本次|这一轮|当前这轮|今天(?:只|先)?|暂时|临时|this time|"
    r"for this (?:turn|request)|today only|temporarily)",
    re.IGNORECASE,
)
_PROFILE_PATTERNS = (
    (
        "background",
        re.compile(
            r"^(?:我是|我的工作是|我的职责是|我负责|我主要负责|我从事|我做的是)"
            r"[：:，,\s]*(.+)$",
            re.IGNORECASE,
        ),
        "User background",
        MemoryType.EPISODIC,
        0.55,
        "review",
    ),
    (
        "goal",
        re.compile(r"^(?:我的长期目标是|我的目标是)[：:，,\s]*(.+)$", re.IGNORECASE),
        "User goal",
        MemoryType.EPISODIC,
        0.55,
        "review",
    ),
    (
        "background",
        re.compile(
            r"^(?:i am|i work as|i am responsible for)[,:\s]+(.+)$",
            re.IGNORECASE,
        ),
        "User background",
        MemoryType.EPISODIC,
        0.55,
        "review",
    ),
    (
        "goal",
        re.compile(r"^(?:my long-term goal is|my goal is)[,:\s]+(.+)$", re.IGNORECASE),
        "User goal",
        MemoryType.EPISODIC,
        0.55,
        "review",
    ),
    (
        "interest",
        re.compile(
            r"^我(?:主要|长期|持续|平时|比较)?(?:关注|关心)[：:，,\s]*(.+)$",
            re.IGNORECASE,
        ),
        "User interest",
        MemoryType.EPISODIC,
        0.65,
        "review",
    ),
    (
        "interest",
        re.compile(r"^我对[：:，,\s]*(.+?)[，,\s]*感兴趣$", re.IGNORECASE),
        "User interest",
        MemoryType.EPISODIC,
        0.65,
        "review",
    ),
    (
        "preference",
        re.compile(r"^(?:我(?:更)?喜欢|我习惯)[：:，,\s]*(.+)$", re.IGNORECASE),
        "",
        MemoryType.PREFERENCE,
        0.8,
        "auto_confirm",
    ),
    (
        "preference",
        re.compile(
            r"^我希望(?:你)?(?:以后|今后|回复时|回答时|分析时|沟通时)[：:，,\s]*(.+)$",
            re.IGNORECASE,
        ),
        "",
        MemoryType.PREFERENCE,
        0.8,
        "auto_confirm",
    ),
    (
        "interest",
        re.compile(r"^(?:i follow|i care about|i am interested in)[,:\s]+(.+)$", re.IGNORECASE),
        "User interest",
        MemoryType.EPISODIC,
        0.65,
        "review",
    ),
    (
        "preference",
        re.compile(r"^(?:i prefer|i like)[,:\s]+(.+)$", re.IGNORECASE),
        "",
        MemoryType.PREFERENCE,
        0.8,
        "auto_confirm",
    ),
)
_PORTFOLIO_POSITION = re.compile(
    r"^(?:我(?:现在|目前)?持有|我手里有|我的持仓(?:是|为)?|"
    r"i\s+(?:currently\s+)?(?:hold|own)|my\s+(?:current\s+)?(?:position|holding)\s+is)"
    r"[：:，,\s]*"
    r"(?P<asset>[A-Za-z0-9.\-\u4e00-\u9fff ]{1,40}?)\s*"
    r"(?P<amount>\d[\d,.]*)\s*(?P<unit>股|份|枚|个|shares?|units?)"
    r"(?P<details>.*)$",
    re.IGNORECASE,
)
_PORTFOLIO_PREFIX = "Portfolio position ["
_STATEMENT_BOUNDARY = re.compile(r"[。！？!?;；\n]+")
_MAX_CANDIDATES_PER_MESSAGE = 8


class MemoryCandidateDecision(StrEnum):
    AUTO_CONFIRM = "auto_confirm"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class UserProfileCandidate:
    category: str
    text: str
    memory_type: MemoryType
    confidence: float
    decision: MemoryCandidateDecision


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
    if not normalized:
        return ()
    candidates: list[UserProfileCandidate] = []
    seen: set[tuple[str, str]] = set()
    for statement in _STATEMENT_BOUNDARY.split(normalized):
        candidate = _candidate_from_statement(statement.strip())
        if candidate is None:
            continue
        key = candidate.category, candidate.text.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
        if len(candidates) == _MAX_CANDIDATES_PER_MESSAGE:
            break
    return tuple(candidates)


def _candidate_from_statement(normalized: str) -> UserProfileCandidate | None:
    if not normalized or _TEMPORARY.search(normalized):
        return None
    if match := _PORTFOLIO_POSITION.fullmatch(normalized):
        asset = _clean_portfolio_part(match.group("asset"))
        amount = _clean_portfolio_part(match.group("amount"))
        unit = _clean_portfolio_part(match.group("unit"))
        details = match.group("details").strip(" ，,。")
        value = safe_memory_text(
            f"{_PORTFOLIO_PREFIX}{asset}]: {amount} {unit}"
            + (f", {details}" if details else "")
        )
        if value is None:
            return None
        return UserProfileCandidate(
            "portfolio",
            value,
            MemoryType.EPISODIC,
            0.8,
            MemoryCandidateDecision.REVIEW,
        )
    for category, pattern, label, memory_type, confidence, decision in _PROFILE_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is None:
            continue
        value = safe_memory_text(match.group(1))
        if value is None:
            return None
        text = f"{label}: {value}" if label else value
        return UserProfileCandidate(
            category,
            text,
            memory_type,
            confidence,
            MemoryCandidateDecision(decision),
        )
    return None


def dynamic_memory_subject(text: str) -> str | None:
    """Return the stable subject of a canonical dynamic user fact."""
    if not text.startswith(_PORTFOLIO_PREFIX):
        return None
    subject, separator, _ = text.removeprefix(_PORTFOLIO_PREFIX).partition("]:")
    normalized = " ".join(subject.split()).casefold()
    return f"portfolio:{normalized}" if separator and normalized else None


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
        ("User interest: ", "interest"),
        (_PORTFOLIO_PREFIX, "portfolio"),
    ):
        if record.memory_type is MemoryType.EPISODIC and record.text.startswith(prefix):
            text = record.text.removeprefix(prefix)
            return category, text if category != "portfolio" else text.replace("]: ", "：", 1)
    return None, record.text


def _clean_portfolio_part(value: str) -> str:
    return " ".join(value.strip().split())
