import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.messages import SessionMessage
from agent_core.harness.models import HarnessContext
from agent_core.harness.retry_plan import build_retry_plan_hint
from agent_core.ports.conversation_compactor import ConversationCompactionResult


@dataclass(frozen=True)
class PlannerResult:
    summary: str
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("planner result summary must not be blank")


@dataclass(frozen=True)
class VerifierResult:
    summary: str
    passed: bool
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("verifier result summary must not be blank")


class PlannerHook(Protocol):
    def plan(self, context: HarnessContext) -> PlannerResult: ...


class VerifierHook(Protocol):
    def verify(
        self,
        context: HarnessContext,
        tool_status: str,
        tool_output: str,
    ) -> VerifierResult: ...


class CompactionHook(Protocol):
    def pre_compact(
        self,
        messages: tuple[SessionMessage, ...],
        *,
        max_tokens: int,
    ) -> None: ...

    def post_compact(self, result: ConversationCompactionResult) -> None: ...


@dataclass(frozen=True)
class NoopPlanner:
    def plan(self, context: HarnessContext) -> PlannerResult:
        if context.task.runtime_evidence:
            retry_hint = build_retry_plan_hint(context.task.runtime_evidence)
            return PlannerResult(
                summary=retry_hint.summary,
                metadata={
                    "attempt_number": context.attempt.number,
                    "accepted_constraints": list(retry_hint.accepted_constraints),
                    "prior_tool_outputs": list(retry_hint.prior_tool_outputs),
                    "retry_blockers": list(retry_hint.blockers),
                    "retry_focus": list(retry_hint.focus),
                },
            )
        return PlannerResult(
            summary="planner hook skipped",
            metadata={"attempt_number": context.attempt.number},
        )


@dataclass(frozen=True)
class NoopVerifier:
    def verify(
        self,
        context: HarnessContext,
        tool_status: str,
        tool_output: str,
    ) -> VerifierResult:
        return VerifierResult(
            summary="verifier hook skipped",
            passed=tool_status == "executed",
            metadata={
                "attempt_number": context.attempt.number,
                "tool_output": tool_output,
            },
        )

# ---------------------------------------------------------------------------
# EXT-HOOK-01: declarative, deterministic extension hooks (ADR-014).
# Hooks never bypass Policy and never mutate result facts; every kind carries
# an explicit fail-open/fail-closed classification with bounded timeouts.
# ---------------------------------------------------------------------------

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class HookKind(StrEnum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    STOP = "stop"
    SESSION_START = "session_start"
    ARTIFACT_CREATED = "artifact_created"


class HookFailureMode(StrEnum):
    FAIL_OPEN = "fail-open"
    FAIL_CLOSED = "fail-closed"


_KIND_FAILURE_MODES: dict[HookKind, HookFailureMode] = {
    HookKind.PRE_TOOL_USE: HookFailureMode.FAIL_CLOSED,
    HookKind.POST_TOOL_USE: HookFailureMode.FAIL_OPEN,
    HookKind.STOP: HookFailureMode.FAIL_CLOSED,
    HookKind.SESSION_START: HookFailureMode.FAIL_OPEN,
    HookKind.ARTIFACT_CREATED: HookFailureMode.FAIL_OPEN,
}


class HookDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class HookDefinition(BaseModel):
    """One declarative hook bound to a package digest with stable ordering."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: HookKind
    package_digest: str
    order: int = Field(default=0, ge=0, le=9_999)
    timeout_ms: int = Field(default=2_000, ge=1, le=30_000)
    tool_matchers: tuple[str, ...] = ()

    @field_validator("name")
    @classmethod
    def require_name(cls, value: str) -> str:
        if not _NAME_PATTERN.fullmatch(value):
            raise ValueError("hook name must be lowercase kebab-case")
        return value

    @field_validator("package_digest")
    @classmethod
    def require_digest(cls, value: str) -> str:
        if not _DIGEST_PATTERN.fullmatch(value):
            raise ValueError("hook package_digest must be sha256:<64 hex>")
        return value

    @model_validator(mode="after")
    def validate_kind_rules(self) -> "HookDefinition":
        if self.kind is HookKind.PRE_TOOL_USE and not self.tool_matchers:
            raise ValueError("pre_tool_use hooks require at least one tool matcher")
        if self.kind is not HookKind.PRE_TOOL_USE and self.tool_matchers:
            raise ValueError("tool matchers only apply to pre_tool_use hooks")
        return self

    @property
    def failure_mode(self) -> HookFailureMode:
        return _KIND_FAILURE_MODES[self.kind]

    def sort_key(self) -> tuple[int, str]:
        return self.order, self.name

    def matches_tool(self, tool_name: str) -> bool:
        if self.kind is not HookKind.PRE_TOOL_USE:
            return False
        return any(
            re.fullmatch(matcher.replace("*", ".*"), tool_name)
            for matcher in self.tool_matchers
        )


class HookOutcome(BaseModel):
    """Deterministic result; audit text never mutates execution facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hook_name: str
    decision: HookDecision
    reason: str = ""
    audit: tuple[str, ...] = ()
    failed: bool = False
    failure_mode: HookFailureMode | None = None

    @model_validator(mode="after")
    def validate_decision_shape(self) -> "HookOutcome":
        if self.decision is not HookDecision.ALLOW and not self.reason.strip():
            raise ValueError("deny and require_approval outcomes require a reason")
        if self.failed and self.failure_mode is None:
            raise ValueError("failed outcomes must carry their failure mode")
        return self


def order_hooks(hooks: tuple[HookDefinition, ...]) -> tuple[HookDefinition, ...]:
    """Stable deterministic ordering: order, name, then package digest."""
    return tuple(
        sorted(hooks, key=lambda hook: (*hook.sort_key(), hook.package_digest))
    )


def resolve_pre_tool_decision(outcomes: tuple[HookOutcome, ...]) -> HookDecision:
    """deny > require_approval > allow across ordered pre_tool_use outcomes."""
    decisions = {outcome.decision for outcome in outcomes}
    if HookDecision.DENY in decisions:
        return HookDecision.DENY
    if HookDecision.REQUIRE_APPROVAL in decisions:
        return HookDecision.REQUIRE_APPROVAL
    return HookDecision.ALLOW
