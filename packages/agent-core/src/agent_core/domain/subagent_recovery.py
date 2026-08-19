"""Deterministic delegation recovery semantics (SUBAGENT-RECOVERY-01).

Plan section 15: a crashed parent never orphans a running child; a crashed
child is reclaimed after lease expiry; cancels propagate parent→child and
stop new model/tool calls. This module turns those rows of the failure
table into one deterministic function over durable facts — no runtime
guesswork, no special cases in workers.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from agent_core.domain.identifiers import TaskId
from agent_core.domain.parent_continuation import (
    ChildTerminalRecord,
    ContinuationDecision,
    ParentContinuation,
    evaluate_wakeup,
)


class RecoveryAction(StrEnum):
    """The bounded set of recovery moves (plan 15)."""

    AWAIT_CHILD_TERMINAL = "await_child_terminal"
    RECLAIM_CHILD_LEASE = "reclaim_child_lease"
    PROPAGATE_CANCEL_TO_CHILD = "propagate_cancel_to_child"
    EMIT_CANCELLED_CHILD_RECEIPT = "emit_cancelled_child_receipt"
    RESUME_PARENT = "resume_parent"


class DelegationRecoveryState(BaseModel):
    """Durable facts about one parent-child edge at recovery time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_task_id: TaskId
    child_task_id: TaskId
    delegation_id: str = Field(min_length=1, max_length=128)
    child_terminal: ChildTerminalRecord | None = None
    parent_continuation: ParentContinuation | None = None
    parent_cancel_requested: bool = False
    child_cancel_requested: bool = False

    @classmethod
    def after_parent_crash(
        cls,
        *,
        parent_task_id: TaskId,
        child_task_id: TaskId,
        delegation_id: str,
        continuation: ParentContinuation | None,
    ) -> Self:
        """Parent crashed after delegation; the child keeps running."""

        return cls(
            parent_task_id=parent_task_id,
            child_task_id=child_task_id,
            delegation_id=delegation_id,
            parent_continuation=continuation,
        )


class RecoveryPlan(BaseModel):
    """The deterministic outcome for one recovery evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actions: tuple[RecoveryAction, ...]
    stop_new_child_calls: bool = False
    reason_code: str = Field(min_length=1, max_length=128)


def resolve_recovery(state: DelegationRecoveryState) -> RecoveryPlan:
    """Map durable facts to the plan-15 failure-table row, deterministically."""

    if state.child_terminal is None:
        if state.parent_cancel_requested or state.child_cancel_requested:
            # Cancel reaches the child boundary: no new model/tool calls,
            # then the child emits its cancelled receipt when it stops.
            return RecoveryPlan(
                actions=(
                    RecoveryAction.PROPAGATE_CANCEL_TO_CHILD,
                    RecoveryAction.EMIT_CANCELLED_CHILD_RECEIPT,
                ),
                stop_new_child_calls=True,
                reason_code="cancel_propagated_to_child",
            )
        if state.parent_continuation is not None:
            # Parent crashed after delegation: the child keeps running and
            # the continuation wakes the parent at terminal time.
            return RecoveryPlan(
                actions=(RecoveryAction.AWAIT_CHILD_TERMINAL,),
                reason_code="child_running_parent_waiting",
            )
        # No continuation registered: the child lease is the recovery
        # authority — another worker reclaims it after expiry.
        return RecoveryPlan(
            actions=(RecoveryAction.RECLAIM_CHILD_LEASE,),
            reason_code="child_lease_recovery",
        )

    terminal = state.child_terminal
    if terminal.status.value == "cancelled":
        return RecoveryPlan(
            actions=(RecoveryAction.RESUME_PARENT,),
            reason_code="child_cancelled_parent_resumes",
        )
    continuation = state.parent_continuation
    if continuation is None:
        # Child settled without a registered continuation: resume the
        # parent directly from the terminal record.
        return RecoveryPlan(
            actions=(RecoveryAction.RESUME_PARENT,),
            reason_code="child_terminal_no_continuation",
        )
    wakeup = evaluate_wakeup(continuation, (terminal,))
    if wakeup is None:
        return RecoveryPlan(
            actions=(RecoveryAction.AWAIT_CHILD_TERMINAL,),
            reason_code="strategy_not_settled",
        )
    return RecoveryPlan(
        actions=(RecoveryAction.RESUME_PARENT,),
        reason_code="strategy_settled_parent_resumes",
    )


def continuation_decision_for(
    continuation: ParentContinuation,
    terminals: tuple[ChildTerminalRecord, ...],
) -> ContinuationDecision:
    """Expose the strategy decision for audit paths."""

    return continuation.evaluate(terminals)[0]
