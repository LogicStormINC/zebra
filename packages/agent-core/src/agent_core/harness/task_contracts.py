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
    max_characters: int | None = None
    required_answer_terms: tuple[str, ...] = ()
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
        if self.max_characters is not None and self.max_characters < self.min_characters:
            raise ValueError("task acceptance max_characters must not be below minimum")
        if any(not item.strip() for item in self.required_answer_terms):
            raise ValueError("task acceptance required answer terms must not be blank")
        if not self.required_outcomes or any(not item.strip() for item in self.required_outcomes):
            raise ValueError("task acceptance outcomes must not be blank")


def infer_task_contract(user_input: str) -> TaskAcceptanceContract:
    lowered = user_input.lower()
    max_characters = _inferred_max_characters(lowered)
    brief = _contains_any(lowered, ("简短", "简洁", "一句话", "brief", "concise")) or (
        max_characters is not None
        and max_characters <= 500
        and _contains_any(lowered, ("一段", "摘要", "paragraph", "summary"))
    )
    # ponytail: 报告 also means reporting a result; it cannot alone mandate
    # document length/structure. Explicit format hints and Host contracts remain authoritative.
    deliverable = _contains_any(
        lowered,
        ("文章", "研判", "markdown", "详细", "完整", "方案", "计划", "detailed"),
    )
    structured = _contains_any(lowered, ("markdown", "方案", "计划", "分点", "列表"))
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
    min_characters = 1 if brief else 160 if deliverable or (current and analytical) else 1
    if max_characters is not None:
        min_characters = min(min_characters, max_characters)
    requires_verification = task_type in {AgentTaskType.CHANGE, AgentTaskType.OPERATE}
    requires_evidence = evidence or current or task_type is AgentTaskType.RESEARCH
    requires_citation = (
        _contains_any(lowered, ("来源", "引用", "链接", "source", "citation", "link")) or current
    )
    outcomes = ["answer_present"]
    if requires_evidence:
        outcomes.append("evidence_collected")
    if task_type is AgentTaskType.CHANGE:
        outcomes.append("change_applied")
    if task_type is AgentTaskType.CREATE:
        outcomes.append("artifact_produced")
    if task_type is AgentTaskType.OPERATE:
        outcomes.append("operation_completed")
    if requires_verification:
        outcomes.append("result_verified")
    return TaskAcceptanceContract(
        task_type=task_type,
        goal=user_input.strip(),
        required_outcomes=tuple(outcomes),
        min_characters=min_characters,
        max_characters=max_characters,
        require_structure=(structured or (current and analytical)) and not brief,
        require_evidence_reference=requires_evidence,
        require_matching_citation=requires_citation,
        require_verification=requires_verification,
        require_artifact=task_type is AgentTaskType.CREATE,
    )


def parse_task_contract(
    value: Mapping[str, object], *, fallback_goal: str
) -> TaskAcceptanceContract:
    goal = _bounded_text(value.get("goal"), fallback_goal, limit=4_000)
    inferred = infer_task_contract(goal)
    raw_type = value.get("taskType", value.get("task_type", inferred.task_type.value))
    try:
        task_type = AgentTaskType(str(raw_type))
    except ValueError as exc:
        raise ValueError("task acceptance task_type is invalid") from exc
    raw_outcomes = value.get("requiredOutcomes", value.get("required_outcomes"))
    outcomes = inferred.required_outcomes
    if raw_outcomes is not None:
        if not isinstance(raw_outcomes, list) or len(raw_outcomes) > 12:
            raise ValueError("task acceptance required_outcomes is invalid")
        outcomes = tuple(_bounded_text(item, "", limit=160) for item in raw_outcomes)
    raw_terms = value.get("requiredAnswerTerms", value.get("required_answer_terms", []))
    if not isinstance(raw_terms, list) or len(raw_terms) > 20:
        raise ValueError("task acceptance required_answer_terms is invalid")
    required_terms = tuple(_bounded_text(item, "", limit=160) for item in raw_terms)
    max_characters = _optional_positive_int(
        value.get("maxCharacters", value.get("max_characters")),
        inferred.max_characters,
        20_000,
    )
    return TaskAcceptanceContract(
        task_type=task_type,
        goal=goal,
        required_outcomes=outcomes,
        min_characters=_positive_int(value.get("minCharacters"), inferred.min_characters, 8_000),
        max_characters=max_characters,
        required_answer_terms=required_terms,
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
    # ponytail: bounded negated-action phrases, not semantic intent parsing;
    # explicit acceptance contracts remain authoritative for ambiguous requests.
    # Object-separated prohibitions ("不得把冲突记录删除") end at the action,
    # punctuation or contrast; later affirmative actions must remain visible.
    action_text = re.sub(
        r"(?:不要|不允许|禁止|无需|不用|不得)(?:把|将|对|给)"
        r"(?:(?!而是|但是|然后|并且|但)[^，。；!?！？\n]){0,160}?"
        r"(?:修复|修改|实现|删除|增加|改成|创建|部署|发布|提交|发送|执行)",
        "",
        text,
    )
    action_text = re.sub(
        r"(?:不要|不允许|禁止|无需|不用|不得|不)(?:再|去|进行|任何)?"
        r"(?:修复|修改|实现|删除|增加|改成|创建|部署|发布|提交|发送|执行)"
        r"|\b(?:do not|don't|never|without)\s+(?:fix(?:ing)?|chang(?:e|ing)|"
        r"implement(?:ing)?|delet(?:e|ing)|creat(?:e|ing)|deploy(?:ing)?|"
        r"publish(?:ing)?|submit(?:ting)?|execut(?:e|ing))\b",
        "",
        action_text,
    )
    information_request = _contains_any(
        text,
        (
            "如何",
            "怎么",
            "是否",
            "为什么",
            "是什么",
            "介绍",
            "解释",
            "评估",
            "how to",
            "should i",
            "what is",
            "explain",
            "evaluate",
        ),
    )
    explicit_action = _contains_any(
        action_text,
        (
            "请部署",
            "请发布",
            "请提交",
            "请修复",
            "请修改",
            "请实现",
            "请创建",
            "帮我部署",
            "帮我修复",
            "开始部署",
            "开始修复",
            "开始实施",
            "并修复",
            "并修改",
            "并部署",
            "please deploy",
            "please publish",
            "please submit",
            "please fix",
            "please change",
            "please implement",
            "please create",
        ),
    )
    # ponytail: only explicit artifact publication is creation, not deployment.
    # Other operations in the same request still retain operational verification.
    # With files.publish, an extension-qualified file object is an Artifact;
    # ambiguous publication or an external destination still needs verification.
    if re.search(r"\bfiles\.publish\b", action_text):
        action_text = re.sub(
            r"发布(?:以下|这)?[一二三四五六七八九十两\d]*(?:个|份)?\s*"
            r"\.[a-z0-9.]{1,24}\s*文件(?=\s*(?:[，。；!?！？\n]|$))"
            r"|\bpublish\s+(?:(?:a|an|the|one|two|three|\d+)\s+)?"
            r"\.[a-z0-9.]{1,24}\s+files?\b(?=\s*(?:[,.;!?]|and\b|then\b|$))",
            "",
            action_text,
        )
    operation_text, artifact_publications = re.subn(
        r"发布(?:为|成|一个|为一个)?\s*(?:json\s*)?artifact\b"
        r"|\bpublish\s+(?:(?:a|an|the)\s+)?(?:json\s+)?artifact\b"
        r"|\bfiles\.publish\b",
        "",
        action_text,
    )
    operational_request = _contains_any(
        operation_text,
        (
            "部署",
            "发布",
            "提交",
            "发送",
            "调度",
            "定时任务",
            "deploy",
            "publish",
            "submit",
            "schedule",
            "scheduled job",
        ),
    ) or _explicit_execute_request(operation_text)
    if (not information_request or explicit_action) and operational_request:
        return AgentTaskType.OPERATE
    if (not information_request or explicit_action) and _contains_any(
        action_text,
        ("修复", "修改", "实现", "删除", "增加", "改成", "fix", "change", "implement", "delete"),
    ):
        return AgentTaskType.CHANGE
    if (not information_request or explicit_action) and (
        artifact_publications or _contains_any(
            action_text, ("创建", "生成文件", "写一篇", "create", "generate a file")
        )
    ):
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


def _explicit_execute_request(text: str) -> bool:
    """Distinguish an execution command from prose describing prior execution."""

    return (
        re.search(
            r"(?:^|[，。；：!?！？\n])\s*(?:请|请帮我|帮我|现在|立即|开始)?执行"
            r"(?:一次|一下|以下|这个|该|上述|命令|任务|操作|计划|方案|测试|验收|查询|调用|\s|$)",
            text,
        )
        is not None
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


def _optional_positive_int(value: object, fallback: int | None, maximum: int) -> int | None:
    if value is None:
        return fallback
    if type(value) is not int or not 0 < value <= maximum:
        raise ValueError("task acceptance integer is invalid")
    return value


def _inferred_max_characters(text: str) -> int | None:
    patterns = (
        r"(?:不超过|最多|限制在)\s*(\d{1,5})\s*(?:个?字|字符)",
        r"(?:no more than|at most|within)\s+(\d{1,5})\s+(?:chinese\s+)?characters?",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match is not None:
            limit = int(match.group(1))
            return limit if 0 < limit <= 20_000 else None
    return None


def _flag(value: Mapping[str, object], key: str, fallback: bool) -> bool:
    raw = value.get(key)
    if raw is None:
        return fallback
    if type(raw) is not bool:
        raise ValueError(f"task acceptance {key} must be boolean")
    return raw
