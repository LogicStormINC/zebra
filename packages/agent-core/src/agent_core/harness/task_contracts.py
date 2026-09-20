"""Typed, Host-overridable completion contract for one Agent task."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class AgentTaskType(StrEnum):
    ANSWER = "answer"
    RESEARCH = "research"
    CHANGE = "change"
    CREATE = "create"
    OPERATE = "operate"


@dataclass(frozen=True)
class TaskAcceptanceContract:
    task_type: AgentTaskType
    goal: str
    required_outcomes: tuple[str, ...] = ("answer_present",)
    min_characters: int = 1
    require_structure: bool = False
    require_evidence_reference: bool = False
    require_matching_citation: bool = False
    require_verification: bool = False
    require_artifact: bool = False

    def __post_init__(self) -> None:
        if not self.goal.strip():
            raise ValueError("task acceptance goal must not be blank")
        if self.min_characters <= 0:
            raise ValueError("task acceptance min_characters must be positive")
        if not self.required_outcomes or any(not item.strip() for item in self.required_outcomes):
            raise ValueError("task acceptance outcomes must not be blank")


def infer_task_contract(user_input: str) -> TaskAcceptanceContract:
    lowered = user_input.lower()
    brief = _contains_any(lowered, ("简短", "简洁", "一句话", "brief", "concise"))
    deliverable = _contains_any(
        lowered,
        ("报告", "文章", "研判", "markdown", "详细", "完整", "方案", "计划", "detailed"),
    )
    structured = _contains_any(lowered, ("报告", "markdown", "方案", "计划", "分点", "列表"))
    evidence = _contains_any(
        lowered,
        ("证据", "来源", "引用", "链接", "验证", "evidence", "source", "citation", "verify"),
    )
    current = _contains_any(
        lowered,
        (
            "最近",
            "近期",
            "最新",
            "当前",
            "今天",
            "现在",
            "实时",
            "变化",
            "recent",
            "latest",
            "current",
            "today",
            "now",
            "real-time",
        ),
    )
    analytical = _contains_any(
        lowered, ("分析", "研判", "比较", "变化", "趋势", "影响", "analysis", "compare")
    )
    task_type = _task_type(lowered)
    requires_verification = task_type in {AgentTaskType.CHANGE, AgentTaskType.OPERATE}
    requires_evidence = evidence or current or task_type is AgentTaskType.RESEARCH
    requires_citation = (
        _contains_any(lowered, ("来源", "引用", "链接", "source", "citation", "link")) or current
    )
    outcomes = ["answer_present"]
    if requires_evidence:
        outcomes.append("evidence_collected")
    if requires_verification:
        outcomes.append("result_verified")
    return TaskAcceptanceContract(
        task_type=task_type,
        goal=user_input.strip(),
        required_outcomes=tuple(outcomes),
        min_characters=(1 if brief else 160 if deliverable or (current and analytical) else 1),
        require_structure=(structured or (current and analytical)) and not brief,
        require_evidence_reference=requires_evidence,
        require_matching_citation=requires_citation,
        require_verification=requires_verification,
    )


def parse_task_contract(
    value: Mapping[str, object], *, fallback_goal: str
) -> TaskAcceptanceContract:
    inferred = infer_task_contract(fallback_goal)
    raw_type = value.get("taskType", value.get("task_type", inferred.task_type.value))
    try:
        task_type = AgentTaskType(str(raw_type))
    except ValueError as exc:
        raise ValueError("task acceptance task_type is invalid") from exc
    goal = _bounded_text(value.get("goal"), fallback_goal, limit=4_000)
    raw_outcomes = value.get("requiredOutcomes", value.get("required_outcomes"))
    outcomes = inferred.required_outcomes
    if raw_outcomes is not None:
        if not isinstance(raw_outcomes, list) or len(raw_outcomes) > 12:
            raise ValueError("task acceptance required_outcomes is invalid")
        outcomes = tuple(_bounded_text(item, "", limit=160) for item in raw_outcomes)
    return TaskAcceptanceContract(
        task_type=task_type,
        goal=goal,
        required_outcomes=outcomes,
        min_characters=_positive_int(value.get("minCharacters"), inferred.min_characters, 8_000),
        require_structure=_flag(value, "requireStructure", inferred.require_structure),
        require_evidence_reference=_flag(
            value, "requireEvidence", inferred.require_evidence_reference
        ),
        require_matching_citation=_flag(
            value, "requireCitations", inferred.require_matching_citation
        ),
        require_verification=_flag(value, "requireVerification", inferred.require_verification),
        require_artifact=_flag(value, "requireArtifact", inferred.require_artifact),
    )


def _task_type(text: str) -> AgentTaskType:
    if _contains_any(text, ("部署", "发布", "提交", "发送", "执行", "deploy", "publish", "submit")):
        return AgentTaskType.OPERATE
    if _contains_any(
        text,
        ("修复", "修改", "实现", "删除", "增加", "改成", "fix", "change", "implement", "delete"),
    ):
        return AgentTaskType.CHANGE
    if _contains_any(text, ("创建", "生成文件", "写一篇", "create", "generate a file")):
        return AgentTaskType.CREATE
    if _contains_any(
        text, ("调查", "研究", "检索", "最新", "近期", "research", "investigate", "latest")
    ):
        return AgentTaskType.RESEARCH
    return AgentTaskType.ANSWER


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(
        marker in text
        if not marker.isascii()
        else re.search(rf"(?<![a-z0-9_]){re.escape(marker)}(?![a-z0-9_])", text) is not None
        for marker in markers
    )


def _bounded_text(value: object, fallback: str, *, limit: int) -> str:
    text = value.strip() if isinstance(value, str) else fallback.strip()
    if not text or len(text) > limit:
        raise ValueError("task acceptance text is invalid")
    return text


def _positive_int(value: object, fallback: int, maximum: int) -> int:
    if value is None:
        return fallback
    if type(value) is not int or not 0 < value <= maximum:
        raise ValueError("task acceptance integer is invalid")
    return value


def _flag(value: Mapping[str, object], key: str, fallback: bool) -> bool:
    raw = value.get(key)
    if raw is None:
        return fallback
    if type(raw) is not bool:
        raise ValueError(f"task acceptance {key} must be boolean")
    return raw
