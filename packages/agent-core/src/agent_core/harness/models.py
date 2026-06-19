from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session


class HarnessAttemptOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class HarnessStopReason(StrEnum):
    COMPLETED = "completed"
    FAILED_TERMINAL = "failed_terminal"
    RETRY_EXHAUSTED = "retry_exhausted"
    RETRY_ALLOWED = "retry_allowed"


@dataclass(frozen=True)
class HarnessTask:
    title: str
    user_input: str
    max_attempts: int = 1

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("harness task title must not be blank")
        if not self.user_input.strip():
            raise ValueError("harness task user_input must not be blank")
        if self.max_attempts <= 0:
            raise ValueError("harness task max_attempts must be positive")


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
