from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from agent_core.domain.memories import MemoryType


class MemoryDirectiveAction(StrEnum):
    REMEMBER = "remember"
    FORGET = "forget"


@dataclass(frozen=True, slots=True)
class MemoryDirective:
    action: MemoryDirectiveAction
    text: str
    memory_type: MemoryType = MemoryType.PREFERENCE


_FORGET_PATTERNS = (
    re.compile(r"^(?:请)?(?:忘记|删除记忆|不要再记住)[：:，,\s]*(.+)$", re.IGNORECASE),
    re.compile(r"^(?:please\s+)?forget(?:\s+that)?[：:,\s]*(.+)$", re.IGNORECASE),
)
_TYPED_PATTERNS = (
    (
        MemoryType.PROJECT_RULE,
        re.compile(r"^(?:项目约定|项目规则|project\s+rule)[：:\s]+(.+)$", re.IGNORECASE),
    ),
    (
        MemoryType.ARCHITECTURE_FACT,
        re.compile(
            r"^(?:架构决策|架构事实|architecture(?:\s+decision|\s+fact)?)[：:\s]+(.+)$",
            re.IGNORECASE,
        ),
    ),
    (
        MemoryType.PROCEDURE,
        re.compile(r"^(?:操作流程|验证流程|procedure)[：:\s]+(.+)$", re.IGNORECASE),
    ),
)
_REMEMBER_PATTERNS = (
    re.compile(r"^preference\s*:[\s]*(.+)$", re.IGNORECASE),
    re.compile(r"^(?:请)?记住(?:我)?[：:，,\s]*(.+)$", re.IGNORECASE),
    re.compile(r"^(?:我的偏好是|我偏好)[：:，,\s]*(.+)$", re.IGNORECASE),
    re.compile(r"^(?:从现在起|以后|今后|之后)[，,:：\s]*(.+)$", re.IGNORECASE),
    re.compile(r"^(?:please\s+)?remember(?:\s+that)?[：:,\s]*(.+)$", re.IGNORECASE),
    re.compile(r"^from\s+now\s+on[,:\s]+(.+)$", re.IGNORECASE),
)
_SENSITIVE_MARKERS = (
    ".env",
    "api key",
    "apikey",
    "access token",
    "refresh token",
    "private key",
    "password",
    "secret",
    "密码",
    "口令",
    "私钥",
    "令牌",
    "密钥",
)
_BROAD_FORGET_TARGETS = frozenset({"all", "everything", "全部", "所有", "所有记忆"})


def explicit_memory_directive(content: str) -> MemoryDirective | None:
    text = " ".join(content.strip().split())
    if not text:
        return None
    for pattern in _FORGET_PATTERNS:
        if match := pattern.fullmatch(text):
            target = _safe_text(match.group(1))
            if target is None or target.casefold() in _BROAD_FORGET_TARGETS:
                return None
            return MemoryDirective(MemoryDirectiveAction.FORGET, target)
    for memory_type, pattern in _TYPED_PATTERNS:
        if match := pattern.fullmatch(text):
            remembered = _safe_text(match.group(1))
            return (
                None
                if remembered is None
                else MemoryDirective(MemoryDirectiveAction.REMEMBER, remembered, memory_type)
            )
    for pattern in _REMEMBER_PATTERNS:
        if match := pattern.fullmatch(text):
            remembered = _safe_text(match.group(1))
            return (
                None
                if remembered is None
                else MemoryDirective(MemoryDirectiveAction.REMEMBER, remembered)
            )
    return None


def _safe_text(value: str) -> str | None:
    text = value.strip()
    if len(text) < 2 or len(text) > 2000:
        return None
    lowered = text.casefold()
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        return None
    return text
