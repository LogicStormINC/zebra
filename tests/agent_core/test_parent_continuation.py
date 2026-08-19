"""Parent continuation tests: strategies, wakeups, validation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.domain.identifiers import TaskId
from agent_core.domain.parent_continuation import (
    ChildTerminalRecord,
    ChildTerminalStatus,
    ContinuationDecision,
    ParentContinuation,
    evaluate_wakeup,
)
from pydantic import ValidationError

DIGEST = "a" * 64
NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def _new_task() -> TaskId:
    return TaskId(uuid4())


def _continuation(
    *child_ids: TaskId,
    strategy: str = "all_success",
) -> ParentContinuation:
    return ParentContinuation(
        parent_task_id=_new_task(),
        plan_revision=1,
        required_child_ids=child_ids,
        completion_strategy=strategy,  # type: ignore[arg-type]
        resume_command_key="resume-key-1",
        created_at=NOW,
    )


def _terminal(child: TaskId, status: ChildTerminalStatus) -> ChildTerminalRecord:
    return ChildTerminalRecord(
        child_task_id=child,
        status=status,
        result_bundle_digest=DIGEST if status is ChildTerminalStatus.COMPLETED else None,
        terminal_at=NOW,
    )


class TestStrategies:
    def test_all_success_waits_until_every_child_completes(self) -> None:
        a, b = _new_task(), _new_task()
        continuation = _continuation(a, b)
        decision, _ = continuation.evaluate((_terminal(a, ChildTerminalStatus.COMPLETED),))
        assert decision is ContinuationDecision.KEEP_WAITING
        decision, _ = continuation.evaluate(
            (
                _terminal(a, ChildTerminalStatus.COMPLETED),
                _terminal(b, ChildTerminalStatus.COMPLETED),
            )
        )
        assert decision is ContinuationDecision.RESUME

    def test_all_success_settles_when_one_child_fails(self) -> None:
        a, b = _new_task(), _new_task()
        continuation = _continuation(a, b)
        decision, _ = continuation.evaluate(
            (
                _terminal(a, ChildTerminalStatus.FAILED),
                _terminal(b, ChildTerminalStatus.COMPLETED),
            )
        )
        assert decision is ContinuationDecision.RESUME

    def test_any_success_resumes_on_first_completion(self) -> None:
        a, b = _new_task(), _new_task()
        continuation = _continuation(a, b, strategy="any_success")
        decision, _ = continuation.evaluate((_terminal(a, ChildTerminalStatus.COMPLETED),))
        assert decision is ContinuationDecision.RESUME

    def test_unknown_children_cannot_wake_the_parent(self) -> None:
        a = _new_task()
        stranger = _new_task()
        continuation = _continuation(a)
        decision, relevant = continuation.evaluate(
            (_terminal(stranger, ChildTerminalStatus.COMPLETED),)
        )
        assert decision is ContinuationDecision.KEEP_WAITING
        assert relevant == ()


class TestWakeup:
    def test_wakeup_emitted_only_on_settled_strategy(self) -> None:
        a, b = _new_task(), _new_task()
        continuation = _continuation(a, b)
        assert evaluate_wakeup(continuation, (_terminal(a, ChildTerminalStatus.COMPLETED),)) is None
        wakeup = evaluate_wakeup(
            continuation,
            (
                _terminal(a, ChildTerminalStatus.COMPLETED),
                _terminal(b, ChildTerminalStatus.FAILED),
            ),
        )
        assert wakeup is not None
        assert wakeup.any_success is True
        assert wakeup.settled_child_count == 2
        assert wakeup.resume_command_key == "resume-key-1"

    def test_wakeup_all_failed_reports_no_success(self) -> None:
        a = _new_task()
        continuation = _continuation(a)
        wakeup = evaluate_wakeup(continuation, (_terminal(a, ChildTerminalStatus.FAILED),))
        assert wakeup is not None
        assert wakeup.any_success is False


class TestValidation:
    def test_completed_terminal_requires_digest(self) -> None:
        child = _new_task()
        with pytest.raises(ValidationError):
            ChildTerminalRecord(
                child_task_id=child,
                status=ChildTerminalStatus.COMPLETED,
                result_bundle_digest=None,
                terminal_at=NOW,
            )

    def test_duplicate_required_children_rejected(self) -> None:
        child = _new_task()
        with pytest.raises(ValidationError):
            _continuation(child, child)
