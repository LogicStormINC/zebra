from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.plans import SessionPlan
from agent_core.domain.sessions import SessionStatus


class SegmentVisibility(StrEnum):
    INTERNAL = "internal"


class RolloverReason(StrEnum):
    CONTEXT_PRESSURE = "context_pressure"
    RECOVERY = "recovery"
    TERMINAL_FOLLOW_UP = "terminal_follow_up"
    AGENT_HINT = "agent_hint"


class ContextLifecycleDecision(StrEnum):
    CONTINUE = "continue_current_segment"
    COMPACT = "compact_current_segment"
    ROLLOVER = "rollover_internal_segment"
    PAUSE = "pause_for_approval_or_clarification"
    FAIL_CLOSED = "fail_closed"


class AgentTask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: TaskId
    title: str
    goal: str
    task_plan: SessionPlan = Field(default_factory=SessionPlan)
    status: SessionStatus
    active_segment_id: SessionId
    current_sequence: int = Field(ge=0)
    namespace: str = "local"


class ExecutionSegment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    task_id: TaskId
    predecessor_id: SessionId | None = None
    segment_index: int = Field(ge=0)
    visibility: SegmentVisibility = SegmentVisibility.INTERNAL
    rollover_reason: RolloverReason | None = None

    @model_validator(mode="after")
    def validate_predecessor(self) -> ExecutionSegment:
        if (self.segment_index == 0) != (self.predecessor_id is None):
            raise ValueError("only the root Segment may omit its predecessor")
        return self


class ContextLifecycleSignals(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    within_budget: bool = True
    compaction_available: bool = True
    compaction_has_benefit: bool = True
    recovery_requires_new_segment: bool = False
    agent_rollover_hint: bool = False
    pending_tool: bool = False
    pending_approval: bool = False
    pending_clarification: bool = False
    uncertain_effect: bool = False
    authority_or_workspace_drift: bool = False


class ContextLifecycleController:
    def decide(self, signals: ContextLifecycleSignals) -> ContextLifecycleDecision:
        if signals.authority_or_workspace_drift or signals.uncertain_effect:
            return ContextLifecycleDecision.FAIL_CLOSED
        if signals.pending_tool or signals.pending_approval or signals.pending_clarification:
            return ContextLifecycleDecision.PAUSE
        if not signals.within_budget and signals.compaction_available:
            if signals.compaction_has_benefit:
                return ContextLifecycleDecision.COMPACT
        if (
            not signals.within_budget
            or signals.recovery_requires_new_segment
            or signals.agent_rollover_hint
        ):
            return ContextLifecycleDecision.ROLLOVER
        return ContextLifecycleDecision.CONTINUE
