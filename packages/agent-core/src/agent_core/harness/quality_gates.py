"""Small deterministic gates for skill usage and substantive final answers."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerQuality:
    passed: bool
    reason: str


def missing_selected_skills(
    selected: tuple[str, ...],
    metadata: Mapping[str, object],
) -> tuple[str, ...]:
    if not selected:
        return ()
    raw = metadata.get("skill_reads")
    reads = raw if isinstance(raw, dict) else {}
    return tuple(skill for skill in selected if skill not in reads)


def is_substantive_request(user_input: str) -> bool:
    lowered = user_input.lower()
    return any(
        marker in lowered
        for marker in (
            "报告",
            "文章",
            "研判",
            "markdown",
            "详细",
            "完整",
            "分析",
            "detailed",
        )
    )


def evaluate_answer(user_input: str, answer: str) -> AnswerQuality:
    if not answer.strip():
        return AnswerQuality(False, "empty_answer")
    if not is_substantive_request(user_input):
        return AnswerQuality(True, "ordinary_request")
    if len(answer.strip()) < 320:
        return AnswerQuality(False, "deliverable_too_shallow")
    lines = answer.splitlines()
    structured = sum(
        1
        for line in lines
        if line.lstrip().startswith(("#", "-", "*", "1.", "一、", "二、"))
    )
    if len(lines) < 4 or structured == 0:
        return AnswerQuality(False, "deliverable_not_structured")
    return AnswerQuality(True, "structured_deliverable")
