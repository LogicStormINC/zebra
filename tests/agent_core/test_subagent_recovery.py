"""Delegation recovery tests: crash, lease, cancel, resume semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from agent_core.domain.identifiers import TaskId
from agent_core.domain.parent_continuation import (
    ChildTerminalRecord,
    ChildTerminalStatus,
    ParentContinuation,
)
from agent_core.domain.subagent_recovery import (
    DelegationRecoveryState,
    RecoveryAction,
    resolve_recovery,
)

DIGEST = "a" * 64
NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def _continuation(*children: TaskId) -> ParentContinuation:
    return ParentContinuation(
        parent_task_id=TaskId(uuid4()),
        plan_revision=1,
        required_child_ids=children,
        completion_strategy="all_success",
        resume_command_key="resume-key",
        created_at=NOW,
    )


def _state(
    *,
    child: TaskId,
    terminal: ChildTerminalRecord | None,
    continuation: ParentContinuation | None = None,
    parent_cancel: bool = False,
    child_cancel: bool = False,
) -> DelegationRecoveryState:
    return DelegationRecoveryState(
        parent_task_id=TaskId(uuid4()),
        child_task_id=child,
        delegation_id="d" * 64,
        child_terminal=terminal,
        parent_continuation=continuation,
        parent_cancel_requested=parent_cancel,
        child_cancel_requested=child_cancel,
    )


def _terminal(child: TaskId, status: ChildTerminalStatus) -> ChildTerminalRecord:
    return ChildTerminalRecord(
        child_task_id=child,
        status=status,
        result_bundle_digest=DIGEST if status is ChildTerminalStatus.COMPLETED else None,
        terminal_at=NOW,
    )


class TestCrashRecovery:
    def test_parent_crash_leaves_child_running_and_parent_waiting(self) -> None:
        child = TaskId(uuid4())
        state = DelegationRecoveryState.after_parent_crash(
            parent_task_id=TaskId(uuid4()),
            child_task_id=child,
            delegation_id="d" * 64,
            continuation=_continuation(child),
        )
        plan = resolve_recovery(state)
        assert plan.actions == (RecoveryAction.AWAIT_CHILD_TERMINAL,)
        assert plan.reason_code == "child_running_parent_waiting"
        assert not plan.stop_new_child_calls

    def test_child_crash_without_continuation_reclaims_lease(self) -> None:
        child = TaskId(uuid4())
        plan = resolve_recovery(_state(child=child, terminal=None))
        assert plan.actions == (RecoveryAction.RECLAIM_CHILD_LEASE,)
        assert plan.reason_code == "child_lease_recovery"


class TestCancelPropagation:
    def test_parent_cancel_stops_new_child_calls(self) -> None:
        child = TaskId(uuid4())
        plan = resolve_recovery(
            _state(child=child, terminal=None, parent_cancel=True)
        )
        assert RecoveryAction.PROPAGATE_CANCEL_TO_CHILD in plan.actions
        assert RecoveryAction.EMIT_CANCELLED_CHILD_RECEIPT in plan.actions
        assert plan.stop_new_child_calls is True

    def test_child_cancel_request_stops_new_calls(self) -> None:
        child = TaskId(uuid4())
        plan = resolve_recovery(_state(child=child, terminal=None, child_cancel=True))
        assert plan.stop_new_child_calls is True


class TestResume:
    def test_cancelled_child_resumes_parent(self) -> None:
        child = TaskId(uuid4())
        plan = resolve_recovery(
            _state(child=child, terminal=_terminal(child, ChildTerminalStatus.CANCELLED))
        )
        assert plan.actions == (RecoveryAction.RESUME_PARENT,)
        assert plan.reason_code == "child_cancelled_parent_resumes"

    def test_settled_strategy_resumes_parent(self) -> None:
        child = TaskId(uuid4())
        plan = resolve_recovery(
            _state(
                child=child,
                terminal=_terminal(child, ChildTerminalStatus.COMPLETED),
                continuation=_continuation(child),
            )
        )
        assert plan.actions == (RecoveryAction.RESUME_PARENT,)
        assert plan.reason_code == "strategy_settled_parent_resumes"

    def test_unsetted_strategy_keeps_waiting(self) -> None:
        child, other = TaskId(uuid4()), TaskId(uuid4())
        plan = resolve_recovery(
            _state(
                child=child,
                terminal=_terminal(child, ChildTerminalStatus.COMPLETED),
                continuation=_continuation(child, other),
            )
        )
        assert plan.actions == (RecoveryAction.AWAIT_CHILD_TERMINAL,)
        assert plan.reason_code == "strategy_not_settled"

    def test_terminal_without_continuation_resumes_directly(self) -> None:
        child = TaskId(uuid4())
        plan = resolve_recovery(
            _state(child=child, terminal=_terminal(child, ChildTerminalStatus.FAILED))
        )
        assert plan.actions == (RecoveryAction.RESUME_PARENT,)
        assert plan.reason_code == "child_terminal_no_continuation"
