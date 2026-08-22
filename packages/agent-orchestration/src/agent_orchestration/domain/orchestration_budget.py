"""Reservation-and-receipt budget ledger (SUBAGENT-BUDGET-01, plan 13.3).

Budgets are enforced by accounting — never by prompting the model to be
frugal. A parent reserves budget for its children up front; every child
run books actual usage; children can never spend beyond the remaining
reservation.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_REASON_LENGTH = 256


class BudgetExceededError(ValueError):
    """A reservation or booking would exceed the remaining budget."""


class BudgetReservation(BaseModel):
    """One immutable reserved budget envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_tokens: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    runtime_seconds: int = Field(ge=0)

    def covers(self, other: BudgetReservation) -> bool:
        return (
            self.model_tokens >= other.model_tokens
            and self.tool_calls >= other.tool_calls
            and self.runtime_seconds >= other.runtime_seconds
        )

    def minus(self, other: BudgetReservation) -> BudgetReservation:
        return BudgetReservation(
            model_tokens=max(0, self.model_tokens - other.model_tokens),
            tool_calls=max(0, self.tool_calls - other.tool_calls),
            runtime_seconds=max(0, self.runtime_seconds - other.runtime_seconds),
        )


class BudgetUsageReceipt(BaseModel):
    """Actual usage booked by one child run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    child_task_ref: str = Field(min_length=1, max_length=128)
    model_tokens: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    runtime_seconds: int = Field(ge=0)

    def as_reservation(self) -> BudgetReservation:
        return BudgetReservation(
            model_tokens=self.model_tokens,
            tool_calls=self.tool_calls,
            runtime_seconds=self.runtime_seconds,
        )


class BudgetLedger(BaseModel):
    """Deterministic reservation/usage accounting for one parent run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_task_ref: str = Field(min_length=1, max_length=128)
    ceiling: BudgetReservation
    reservations: tuple[BudgetReservation, ...] = ()
    receipts: tuple[BudgetUsageReceipt, ...] = ()

    @model_validator(mode="after")
    def _validate(self) -> Self:
        reserved = self._reserved_unlocked()
        if not self.ceiling.covers(reserved):
            raise ValueError("reservations exceed the budget ceiling")
        return self

    def _reserved_unlocked(self) -> BudgetReservation:
        total = BudgetReservation(model_tokens=0, tool_calls=0, runtime_seconds=0)
        for reservation in self.reservations:
            total = BudgetReservation(
                model_tokens=total.model_tokens + reservation.model_tokens,
                tool_calls=total.tool_calls + reservation.tool_calls,
                runtime_seconds=total.runtime_seconds + reservation.runtime_seconds,
            )
        return total

    def _used(self) -> BudgetReservation:
        total = BudgetReservation(model_tokens=0, tool_calls=0, runtime_seconds=0)
        for receipt in self.receipts:
            used = receipt.as_reservation()
            total = BudgetReservation(
                model_tokens=total.model_tokens + used.model_tokens,
                tool_calls=total.tool_calls + used.tool_calls,
                runtime_seconds=total.runtime_seconds + used.runtime_seconds,
            )
        return total

    @property
    def remaining(self) -> BudgetReservation:
        """Ceiling minus booked usage (reservations still count)."""

        used = self._used()
        unbooked = self._reserved_unlocked().minus(
            used if self._reserved_unlocked().covers(used) else self._reserved_unlocked()
        )
        return self.ceiling.minus(used).minus(unbooked)

    def reserve(self, reservation: BudgetReservation) -> BudgetLedger:
        current = self._reserved_unlocked()
        projected = BudgetReservation(
            model_tokens=current.model_tokens + reservation.model_tokens,
            tool_calls=current.tool_calls + reservation.tool_calls,
            runtime_seconds=current.runtime_seconds + reservation.runtime_seconds,
        )
        if not self.ceiling.covers(projected):
            raise BudgetExceededError(
                "budget reservation exceeds the remaining ceiling"
            )
        return BudgetLedger(
            parent_task_ref=self.parent_task_ref,
            ceiling=self.ceiling,
            reservations=(*self.reservations, reservation),
            receipts=self.receipts,
        )

    def book(self, receipt: BudgetUsageReceipt) -> BudgetLedger:
        used = self._used()
        after = BudgetReservation(
            model_tokens=used.model_tokens + receipt.model_tokens,
            tool_calls=used.tool_calls + receipt.tool_calls,
            runtime_seconds=used.runtime_seconds + receipt.runtime_seconds,
        )
        if not self.ceiling.covers(after):
            raise BudgetExceededError("budget usage exceeds the ceiling")
        return BudgetLedger(
            parent_task_ref=self.parent_task_ref,
            ceiling=self.ceiling,
            reservations=self.reservations,
            receipts=(*self.receipts, receipt),
        )
