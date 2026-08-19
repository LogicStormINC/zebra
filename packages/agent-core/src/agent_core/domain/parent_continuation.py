"""Parent waiting_children continuation (SUBAGENT-PARENT-CONT-01, plan 8.4).

When a parent delegates durably it stops blocking on the child: it records
a continuation, enters ``waiting_children``, releases its Worker lease, and
is resumed by a durable wakeup once the completion strategy is satisfied.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.identifiers import TaskId

MAX_CHILDREN = 16
MAX_KEY_LENGTH = 256


class ContinuationDecision(StrEnum):
    KEEP_WAITING = "keep_waiting"
    RESUME = "resume"


class ChildTerminalStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


CompletionStrategy = Literal["all_success", "all_terminal", "any_success"]


class ChildTerminalRecord(BaseModel):
    """One child's durable terminal outcome as seen by the continuation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    child_task_id: TaskId
    status: ChildTerminalStatus
    result_bundle_digest: str | None = Field(default=None, min_length=64, max_length=64)
    terminal_at: datetime

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.terminal_at.tzinfo is None:
            raise ValueError("child terminal timestamp must be timezone-aware")
        if self.status is ChildTerminalStatus.COMPLETED and not self.result_bundle_digest:
            raise ValueError("completed children must carry a result bundle digest")
        return self


class ParentContinuation(BaseModel):
    """Everything needed to resume a waiting parent (plan 8.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_task_id: TaskId
    plan_revision: int = Field(ge=1)
    required_child_ids: tuple[TaskId, ...] = Field(min_length=1, max_length=MAX_CHILDREN)
    completion_strategy: CompletionStrategy = "all_success"
    resume_command_key: str = Field(min_length=1, max_length=MAX_KEY_LENGTH)
    created_at: datetime

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.created_at.tzinfo is None:
            raise ValueError("continuation created_at must be timezone-aware")
        if len(set(self.required_child_ids)) != len(self.required_child_ids):
            raise ValueError("required children must be unique")
        return self

    def evaluate(
        self,
        terminals: tuple[ChildTerminalRecord, ...],
    ) -> tuple[ContinuationDecision, tuple[ChildTerminalRecord, ...]]:
        """Apply the completion strategy over recorded child terminals.

        Returns the decision plus the terminals that belong to this
        continuation; unknown children are ignored so stray events cannot
        wake a parent early.
        """

        required = set(self.required_child_ids)
        relevant = tuple(
            record for record in terminals if record.child_task_id in required
        )
        seen = {record.child_task_id for record in relevant}
        any_completed = any(
            record.status is ChildTerminalStatus.COMPLETED for record in relevant
        )
        if self.completion_strategy == "any_success":
            # The first success resumes immediately; otherwise wait until
            # every required child is terminal (settled without success).
            if any_completed or seen >= required:
                return ContinuationDecision.RESUME, relevant
            return ContinuationDecision.KEEP_WAITING, relevant
        if not seen >= required:
            return ContinuationDecision.KEEP_WAITING, relevant
        # all_terminal and all_success both settle once every required
        # child reached a terminal state.
        return ContinuationDecision.RESUME, relevant


class ParentWakeup(BaseModel):
    """The durable resume signal produced when a continuation settles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_task_id: TaskId
    resume_command_key: str = Field(min_length=1, max_length=MAX_KEY_LENGTH)
    decision: Literal["resume"]
    settled_child_count: int = Field(ge=1)
    any_success: bool
    emitted_at: datetime

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.emitted_at.tzinfo is None:
            raise ValueError("wakeup emitted_at must be timezone-aware")
        return self


def evaluate_wakeup(
    continuation: ParentContinuation,
    terminals: tuple[ChildTerminalRecord, ...],
    *,
    emitted_at: datetime | None = None,
) -> ParentWakeup | None:
    """Return the durable wakeup once the strategy settles, else None."""

    decision, relevant = continuation.evaluate(terminals)
    if decision is not ContinuationDecision.RESUME:
        return None
    return ParentWakeup(
        parent_task_id=continuation.parent_task_id,
        resume_command_key=continuation.resume_command_key,
        decision="resume",
        settled_child_count=len(relevant),
        any_success=any(
            record.status is ChildTerminalStatus.COMPLETED for record in relevant
        ),
        emitted_at=emitted_at or datetime.now(UTC),
    )
