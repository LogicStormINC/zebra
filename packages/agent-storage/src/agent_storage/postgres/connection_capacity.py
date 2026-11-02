"""Explicit process bulkheads; a permit ends only when its native socket closes."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import Context, ContextVar
from threading import BoundedSemaphore, Lock
from typing import Any, Literal

import psycopg
from psycopg.conninfo import conninfo_to_dict

from agent_storage.postgres.capacity_profile import CapacityProfile

Lane = Literal["normal", "read", "control", "probe"]
_lane: ContextVar[Lane] = ContextVar("postgres_capacity_lane", default="normal")
_budget: ContextVar[ConnectionBudget | None] = ContextVar("postgres_capacity", default=None)
PROFILE_ENV = "ZEBRA_DATABASE_BUDGET_JSON"


class DatabaseCapacityExceeded(TimeoutError):
    """No new socket was admitted; this says nothing about preceding business writes."""


class ConnectionBudget:
    def __init__(self, dsn: str, profile: CapacityProfile, component: str) -> None:
        if component not in profile.fleet or profile.fleet[component] < 1:
            raise ValueError("process component is absent from database budget")
        self.params = conninfo_to_dict(dsn)
        if self.params.get("service"):
            raise ValueError("database budget requires an explicit operator DSN")
        self.profile = profile
        self._lock, self._closed = Lock(), False
        self._slots = {k: BoundedSemaphore(getattr(profile, k))
                       for k in ("normal", "read", "control", "probe")}
        self._active = dict.fromkeys(self._slots, 0)
        self._peak = dict.fromkeys(self._slots, 0)
        self._rejected = dict.fromkeys(self._slots, 0)

    def acquire(self, lane: Lane) -> _Permit:
        if lane not in self._slots:
            raise ValueError("invalid database capacity lane")
        with self._lock:
            if self._closed or not self._slots[lane].acquire(blocking=False):
                self._rejected[lane] += 1
                raise DatabaseCapacityExceeded("database capacity unavailable")
            self._active[lane] += 1
            self._peak[lane] = max(self._peak[lane], self._active[lane])
        return _Permit(self, lane)

    def _release(self, lane: Lane) -> None:
        with self._lock:
            self._active[lane] -= 1
            self._slots[lane].release()

    def stats(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {"active": self._active.copy(), "peak": self._peak.copy(),
                    "rejected": self._rejected.copy()}

    def close(self) -> None:
        # Never cancel a live transaction or claim its socket has exited.
        with self._lock:
            self._closed = True


class _Permit:
    def __init__(self, owner: ConnectionBudget, lane: Lane) -> None:
        self._owner, self._lane = owner, lane
        self._lock, self._released = Lock(), False
        self.attached = False

    def attach(self, connection: Any) -> None:
        connection._capacity_permit = self
        self.attached = True

    def release(self) -> None:
        with self._lock:
            if not self._released:
                self._owner._release(self._lane)
                self._released = True


class CapacityConnection(psycopg.Connection[dict[str, Any]]):
    _capacity_permit: _Permit | None = None

    def close(self) -> None:
        try:
            super().close()
        finally:
            if self.closed and self._capacity_permit is not None:
                self._capacity_permit.release()


def capacity_for(dsn: str, *, strict: bool = True) -> ConnectionBudget | None:
    budget = _budget.get()
    if budget is not None:
        if budget.params != conninfo_to_dict(dsn):
            if strict:
                raise ValueError("database connection is outside the composed budget")
            return None
    elif strict and os.environ.get(PROFILE_ENV):
        raise RuntimeError("database capacity profile has no process composition")
    return budget


def current_lane() -> Lane:
    return _lane.get()


@contextmanager
def capacity_scope(budget: ConnectionBudget | None) -> Iterator[None]:
    token = _budget.set(budget)
    try:
        yield
    finally:
        _budget.reset(token)


@contextmanager
def capacity_lane(lane: Lane) -> Iterator[None]:
    if lane not in ("normal", "read", "control", "probe"):
        raise ValueError("invalid database capacity lane")
    token = _lane.set(lane)
    try:
        yield
    finally:
        _lane.reset(token)


@contextmanager
def reserve(budget: ConnectionBudget | None) -> Iterator[_Permit | None]:
    permit = budget.acquire(current_lane()) if budget is not None else None
    try:
        yield permit
    finally:
        if permit is not None and not permit.attached:
            permit.release()


def connect(
    dsn: str, *, budget: ConnectionBudget | None = None, lane: Lane | None = None, **kwargs: Any
) -> psycopg.Connection[Any]:
    budget = budget if budget is not None else capacity_for(dsn)
    if budget is None:
        return psycopg.connect(dsn, **kwargs)
    if budget.params != conninfo_to_dict(dsn):
        raise ValueError("database connection is outside the composed budget")
    with capacity_lane(lane or current_lane()), reserve(budget) as permit:
        connection = CapacityConnection.connect(dsn, **kwargs)
        assert permit is not None
        permit.attach(connection)
        return connection


def capacity_context() -> Context:
    """Only PG resources cross legacy thread boundaries; no ambient business authority."""
    context = Context()
    context.run(_budget.set, _budget.get())
    context.run(_lane.set, _lane.get())
    return context


def capacity_root_active() -> bool:
    return _budget.get() is not None
