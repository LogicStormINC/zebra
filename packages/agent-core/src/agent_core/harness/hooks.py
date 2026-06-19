from dataclasses import dataclass, field
from typing import Protocol

from agent_core.harness.models import HarnessContext


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


@dataclass(frozen=True)
class NoopPlanner:
    def plan(self, context: HarnessContext) -> PlannerResult:
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
