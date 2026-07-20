from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from agent_core.domain.attachments import AttachmentContextInput
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.plans import SessionPlan
from agent_core.domain.sessions import Session
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
    context_token_budget: int = 200
    runtime_evidence: tuple[RuntimeEvidenceInput, ...] = ()
    confirmed_memories: tuple[ConfirmedMemoryInput, ...] = ()
    attachments: tuple[AttachmentContextInput, ...] = ()
    task_plan: SessionPlan = field(default_factory=SessionPlan)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("harness task title must not be blank")
        if not self.user_input.strip():
            raise ValueError("harness task user_input must not be blank")
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
        object.__setattr__(self, "mcp_allowlist", normalize_mcp_allowlist(self.mcp_allowlist))
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
