from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from agent_core.domain.agent_definitions import AgentDefinition, AgentDefinitionContext
from agent_core.domain.attachments import AttachmentContextInput
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.model_media import ModelMediaInput, ordered_media_inputs
from agent_core.domain.plans import SessionPlan
from agent_core.domain.sessions import Session
from agent_core.domain.skills import (
    SkillComponentIdentity,
    normalize_skill_component_identities,
    normalize_skill_components,
)
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.ports.context_compiler import ConfirmedMemoryInput, RuntimeEvidenceInput


class HarnessAttemptOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SUSPENDED = "suspended"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"


class HarnessStopReason(StrEnum):
    COMPLETED = "completed"
    FAILED_TERMINAL = "failed_terminal"
    MODEL_CALL_BUDGET_EXHAUSTED = "model_call_budget_exhausted"
    RETRY_EXHAUSTED = "retry_exhausted"
    RETRY_ALLOWED = "retry_allowed"
    TOOL_CALL_BUDGET_EXHAUSTED = "tool_call_budget_exhausted"
    TOOL_LOOP_NO_PROGRESS = "tool_loop_no_progress"
    TASK_PLAN_INCOMPLETE = "task_plan_incomplete"
    REQUIRED_PLAN_NOT_CREATED = "required_plan_not_created"
    COMPLETION_EVIDENCE_MISSING = "completion_evidence_missing"
    APPROVAL_REQUIRED = "approval_required"
    CLARIFICATION_REQUIRED = "clarification_required"


@dataclass(frozen=True)
class HarnessTask:
    title: str
    user_input: str
    max_attempts: int = 1
    max_model_calls: int | None = None
    max_tool_calls: int | None = None
    workspace_root: Path | None = None
    policy_profile: str | None = None
    tool_profile: ToolProfile = ToolProfile.GENERAL
    network_profile: str = "none"
    network_allowlist: tuple[str, ...] = ()
    mcp_allowlist: tuple[str, ...] = ()
    preapproved_readonly_tools: tuple[str, ...] = ()
    skill_components: tuple[str, ...] = ()
    skill_component_identities: tuple[SkillComponentIdentity, ...] | None = None
    agent_definition: AgentDefinition | None = None
    agent_context: AgentDefinitionContext | None = None
    model_capabilities: tuple[str, ...] = ()
    model_id: str | None = None
    context_token_budget: int = 200
    runtime_evidence: tuple[RuntimeEvidenceInput, ...] = ()
    confirmed_memories: tuple[ConfirmedMemoryInput, ...] = ()
    attachments: tuple[AttachmentContextInput, ...] = ()
    media_inputs: tuple[ModelMediaInput, ...] = ()
    public_content: str | None = None
    goal: str | None = None
    plan_required: bool = False
    task_plan: SessionPlan = field(default_factory=SessionPlan)
    trusted_evidence_tools: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("harness task title must not be blank")
        if not self.user_input.strip():
            raise ValueError("harness task user_input must not be blank")
        if self.goal is not None:
            normalized_goal = self.goal.strip()
            if not normalized_goal:
                raise ValueError("harness task goal must not be blank when set")
            object.__setattr__(self, "goal", normalized_goal)
        if not isinstance(self.plan_required, bool):
            raise ValueError("harness task plan_required must be boolean")
        if not isinstance(self.trusted_evidence_tools, Mapping):
            raise ValueError("harness task trusted_evidence_tools must be a mapping")
        trusted_evidence_tools: dict[str, tuple[str, ...]] = {}
        for tool_name, labels in self.trusted_evidence_tools.items():
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise ValueError("harness task trusted evidence tool names must be non-blank")
            if not isinstance(labels, Iterable) or isinstance(labels, str | bytes):
                raise ValueError("harness task trusted evidence labels must be a sequence")
            normalized_labels: list[str] = []
            for label in labels:
                if not isinstance(label, str) or not label.strip():
                    raise ValueError(
                        "harness task trusted evidence labels must be non-blank strings"
                    )
                if label.strip() not in normalized_labels:
                    normalized_labels.append(label.strip())
            if normalized_labels:
                trusted_evidence_tools[tool_name.strip()] = tuple(normalized_labels)
        object.__setattr__(
            self,
            "trusted_evidence_tools",
            MappingProxyType(trusted_evidence_tools),
        )
        if self.public_content is not None:
            normalized_public_content = self.public_content.strip()
            if not normalized_public_content:
                raise ValueError("harness task public_content must not be blank")
            if len(normalized_public_content) > 64_000:
                raise ValueError("harness task public_content must not exceed 64000 characters")
            object.__setattr__(self, "public_content", normalized_public_content)
        if self.max_attempts <= 0:
            raise ValueError("harness task max_attempts must be positive")
        if self.max_model_calls is not None and self.max_model_calls <= 0:
            raise ValueError("harness task max_model_calls must be positive when set")
        if self.max_tool_calls is not None and self.max_tool_calls <= 0:
            raise ValueError("harness task max_tool_calls must be positive when set")
        if self.workspace_root is not None and not self.workspace_root.is_absolute():
            raise ValueError("harness task workspace_root must be absolute when set")
        if self.context_token_budget <= 0:
            raise ValueError("harness task context_token_budget must be positive")
        if self.model_id is not None and not self.model_id.strip():
            raise ValueError("harness task model_id must not be blank when set")
        object.__setattr__(self, "mcp_allowlist", normalize_mcp_allowlist(self.mcp_allowlist))
        preapproved_readonly_tools = normalize_mcp_allowlist(
            self.preapproved_readonly_tools
        )
        if preapproved_readonly_tools and (
            self.policy_profile != "read_only"
            or self.network_profile != "mcp-proxy-only"
            or not set(preapproved_readonly_tools) <= set(self.mcp_allowlist)
        ):
            raise ValueError("preapproved read-only tools require scoped Task authority")
        object.__setattr__(
            self, "preapproved_readonly_tools", preapproved_readonly_tools
        )
        object.__setattr__(
            self, "skill_components", normalize_skill_components(self.skill_components)
        )
        skill_component_identities = (
            None
            if self.skill_component_identities is None
            else normalize_skill_component_identities(self.skill_component_identities)
        )
        if skill_component_identities is not None and self.skill_components != tuple(
            identity.name for identity in skill_component_identities
        ):
            raise ValueError("skill component identities must match skill_components")
        object.__setattr__(self, "skill_component_identities", skill_component_identities)
        model_capabilities: list[str] = []
        for capability in self.model_capabilities:
            if not isinstance(capability, str) or not capability.strip():
                raise ValueError("harness task model_capabilities must be non-blank strings")
            normalized = capability.strip()
            if normalized not in model_capabilities:
                model_capabilities.append(normalized)
        object.__setattr__(self, "model_capabilities", tuple(model_capabilities))
        if self.agent_context is not None:
            if self.agent_definition is None:
                raise ValueError("harness task agent_context requires an agent_definition")
            if (
                self.agent_context.agent_id != self.agent_definition.agent_id
                or self.agent_context.version != self.agent_definition.version
            ):
                raise ValueError("harness task agent_context does not match its definition")
        for memory in self.confirmed_memories:
            if not isinstance(memory, ConfirmedMemoryInput):
                raise ValueError(
                    "harness task confirmed_memories must contain ConfirmedMemoryInput values"
                )
            if not memory.text.strip():
                raise ValueError("harness task confirmed_memories must not contain blanks")
        for attachment in self.attachments:
            if not isinstance(attachment, AttachmentContextInput):
                raise ValueError(
                    "harness task attachments must contain AttachmentContextInput values"
                )
        for media_input in self.media_inputs:
            if not isinstance(media_input, ModelMediaInput):
                raise ValueError("harness task media_inputs must contain ModelMediaInput values")
        object.__setattr__(self, "media_inputs", ordered_media_inputs(self.media_inputs))

    @property
    def stable_goal(self) -> str:
        return self.goal or self.user_input


@dataclass(frozen=True)
class HarnessAttempt:
    number: int
    started_at: datetime

    def __post_init__(self) -> None:
        if self.number <= 0:
            raise ValueError("harness attempt number must be positive")
        if self.started_at.tzinfo is None:
            raise ValueError("harness attempt started_at must be timezone-aware")


@dataclass(frozen=True)
class HarnessContext:
    task: HarnessTask
    session: Session
    attempt: HarnessAttempt
    completion_evidence_events: tuple["HarnessEventDraft", ...] = ()


@dataclass(frozen=True)
class HarnessEventDraft:
    event_type: EventType
    actor: EventActor
    payload: dict[str, Any] = field(default_factory=dict)


class HarnessEventBuffer(list[HarnessEventDraft]):
    def __init__(
        self,
        event_sink: Callable[[HarnessEventDraft], None] | None = None,
    ) -> None:
        super().__init__()
        self._event_sink = event_sink

    def append(self, draft: HarnessEventDraft) -> None:
        super().append(draft)
        if self._event_sink is not None:
            self._event_sink(draft)

    def extend(self, drafts: Iterable[HarnessEventDraft]) -> None:
        for draft in drafts:
            self.append(draft)


@dataclass(frozen=True)
class HarnessAttemptResult:
    outcome: HarnessAttemptOutcome
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)
    emitted_events: tuple[HarnessEventDraft, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("harness attempt result summary must not be blank")


@dataclass(frozen=True)
class HarnessRunResult:
    final_outcome: HarnessAttemptOutcome
    stop_reason: HarnessStopReason
    attempts_used: int
    max_attempts: int
    model_calls_used: int
    max_model_calls: int | None
    tool_calls_used: int
    max_tool_calls: int | None
    can_retry: bool
    summary: str
    last_attempt: HarnessAttemptResult

    def __post_init__(self) -> None:
        if self.attempts_used <= 0:
            raise ValueError("harness run result attempts_used must be positive")
        if self.max_attempts <= 0:
            raise ValueError("harness run result max_attempts must be positive")
        if self.attempts_used > self.max_attempts:
            raise ValueError("harness run result attempts_used cannot exceed max_attempts")
        if self.model_calls_used < 0:
            raise ValueError("harness run result model_calls_used cannot be negative")
        if self.tool_calls_used < 0:
            raise ValueError("harness run result tool_calls_used cannot be negative")
        if self.max_model_calls is not None and self.max_model_calls <= 0:
            raise ValueError("harness run result max_model_calls must be positive when set")
        if self.max_tool_calls is not None and self.max_tool_calls <= 0:
            raise ValueError("harness run result max_tool_calls must be positive when set")
        if not self.summary.strip():
            raise ValueError("harness run result summary must not be blank")


@dataclass(frozen=True)
class HarnessToolTrace:
    tool_name: str
    status: str
    arguments: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    policy_decision: str | None = None
    policy_route: str | None = None
    policy_target: str | None = None
    policy_network_profile: str | None = None
    policy_scope: tuple[str, ...] = ()


@dataclass(frozen=True)
class HarnessAttemptTrace:
    attempt_number: int
    assistant_message: str | None = None
    tools: tuple[HarnessToolTrace, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HarnessRunTrace:
    final_outcome: HarnessAttemptOutcome
    stop_reason: HarnessStopReason
    attempts: tuple[HarnessAttemptTrace, ...]


@dataclass(frozen=True)
class HarnessLoopResult:
    session: Session
    events: tuple[SessionEvent, ...]
    attempt_result: HarnessAttemptResult
    attempt_results: tuple[HarnessAttemptResult, ...]
    run_result: HarnessRunResult
