"""Budget ledger tests: reservations, bookings, ceilings."""

from __future__ import annotations

import pytest
from agent_orchestration.domain.orchestration_budget import (
    BudgetExceededError,
    BudgetLedger,
    BudgetReservation,
    BudgetUsageReceipt,
)


def _ceiling() -> BudgetReservation:
    return BudgetReservation(model_tokens=1000, tool_calls=10, runtime_seconds=100)


def test_reserve_within_ceiling_succeeds() -> None:
    ledger = BudgetLedger(parent_task_ref="parent-1", ceiling=_ceiling())
    ledger = ledger.reserve(BudgetReservation(model_tokens=400, tool_calls=4, runtime_seconds=40))
    assert ledger.reservations[-1].model_tokens == 400


def test_reserve_beyond_ceiling_fails_closed() -> None:
    ledger = BudgetLedger(parent_task_ref="parent-1", ceiling=_ceiling())
    with pytest.raises(BudgetExceededError):
        ledger.reserve(BudgetReservation(model_tokens=1001, tool_calls=1, runtime_seconds=1))


def test_booking_beyond_ceiling_fails_closed() -> None:
    ledger = BudgetLedger(parent_task_ref="parent-1", ceiling=_ceiling())
    with pytest.raises(BudgetExceededError):
        ledger.book(
            BudgetUsageReceipt(
                child_task_ref="child-1",
                model_tokens=1001,
                tool_calls=1,
                runtime_seconds=1,
            )
        )


def test_remaining_reflects_usage_and_unbooked_reservations() -> None:
    ledger = BudgetLedger(parent_task_ref="parent-1", ceiling=_ceiling())
    ledger = ledger.reserve(BudgetReservation(model_tokens=500, tool_calls=5, runtime_seconds=50))
    ledger = ledger.book(
        BudgetUsageReceipt(
            child_task_ref="child-1",
            model_tokens=200,
            tool_calls=2,
            runtime_seconds=20,
        )
    )
    assert ledger.remaining.model_tokens == 1000 - 500
    assert ledger.remaining.tool_calls == 10 - 5


def test_ledger_rejects_prebuilt_overreservation() -> None:
    with pytest.raises(ValueError, match="exceed the budget ceiling"):
        BudgetLedger(
            parent_task_ref="parent-1",
            ceiling=_ceiling(),
            reservations=(
                BudgetReservation(model_tokens=600, tool_calls=1, runtime_seconds=1),
                BudgetReservation(model_tokens=600, tool_calls=1, runtime_seconds=1),
            ),
        )
