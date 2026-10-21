"""Explicit database ownership for short phases and existing locked proof transactions."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from re import escape, fullmatch
from threading import get_ident
from typing import Any

from psycopg.conninfo import conninfo_to_dict


@dataclass
class _Unit:
    key: tuple[str, str]
    connection: Any
    thread: int
    active: bool = True
    failed: bool = False


_unit: ContextVar[_Unit | None] = ContextVar("postgres_work_unit", default=None)


def borrow_work_unit(key: tuple[str, str]) -> Any | None:
    unit = _unit.get()
    if unit is None or not unit.active or unit.thread != get_ident() or unit.key != key:
        return None
    return _BorrowUnit(unit)


class _BorrowUnit:
    def __init__(self, unit: _Unit) -> None:
        self.unit = unit
        self.released = False

    def __getattr__(self, name: str) -> Any:
        if self.released or not self.unit.active:
            raise RuntimeError("database work unit borrow has ended")
        if self.unit.thread != get_ident():
            raise RuntimeError("database work unit borrow belongs to another thread")
        if name in {"commit", "rollback", "close", "set_isolation_level", "set_read_only"}:
            raise RuntimeError("nested adapter cannot end or reconfigure a database work unit")
        return getattr(self.unit.connection, name)

    def __enter__(self) -> "_BorrowUnit":
        if self.released or not self.unit.active:
            raise RuntimeError("database work unit borrow has ended")
        if self.unit.thread != get_ident():
            raise RuntimeError("database work unit borrow belongs to another thread")
        return self

    def __exit__(self, kind: Any, error: Any, traceback: Any) -> None:
        self.released = True
        self.unit.failed |= kind is not None


@contextmanager
def postgres_work_unit(database: Any) -> Iterator[None]:
    key = (database._dsn, database.deployment_namespace)
    nested = borrow_work_unit(key)
    if nested is not None:
        with nested:
            yield
        return
    with database.connect() as connection:
        unit = _Unit(key, connection, get_ident())
        token = _unit.set(unit)
        try:
            yield
            if unit.failed:
                raise RuntimeError("database work unit refused after a nested adapter failed")
        finally:
            unit.active = False
            _unit.reset(token)


@contextmanager
def postgres_transaction_work_unit(database: Any, connection: Any) -> Iterator[None]:
    """Borrow the caller's native transaction without committing or releasing it.

    The connection must address the configured database/schema. Namespace is
    still enforced by every native query; this scope grants no execution rights.
    """
    configured = conninfo_to_dict(database._dsn)
    actual = connection.info.get_parameters()
    options = configured.get("options", "")
    actual_options = actual.get("options", "")
    if not isinstance(options, str) or not isinstance(actual_options, str):
        raise ValueError("transaction work unit has invalid connection options")
    # The direct deadline adapter appends only these two equal bounded timeouts.
    # Never ignore arbitrary libpq options: they may change schema or authority.
    options_match = actual_options == options or fullmatch(
        escape(options) + r" -c statement_timeout=([1-9][0-9]*) -c lock_timeout=\1",
        actual_options,
    ) is not None
    from agent_storage.postgres.task_io import TaskIoConnection

    bounded = fullmatch(
        escape(options) + r" -c statement_timeout=([1-9][0-9]*) -c lock_timeout=([1-9][0-9]*)",
        actual_options,
    )
    if isinstance(connection, TaskIoConnection) and bounded is not None:
        options_match |= int(bounded[2]) == min(50, int(bounded[1]))
    if any(actual.get(name) != value for name, value in configured.items()
           if name not in {"password", "connect_timeout", "options"}) or not options_match:
        raise ValueError("transaction work unit belongs to another database or schema")
    key = (database._dsn, database.deployment_namespace)
    current = _unit.get()
    if current is not None and current.active and current.thread == get_ident():
        if current.key == key:
            from agent_storage.postgres.coverage_recovery_preparation import (
                RecoveryDeadlineConnection,
            )

            owner = connection
            while type(owner) is RecoveryDeadlineConnection:
                owner = owner.connection
            if connection is current.connection or (
                isinstance(owner, _BorrowUnit) and owner.unit is current
            ):
                # Exact owner reentry only: a second socket with the same DSN
                # cannot replace the transaction or observe its uncommitted work.
                with _BorrowUnit(current):
                    yield
                return
            raise RuntimeError("transaction work unit already has an owner")
    unit = _Unit(key, connection, get_ident())
    token = _unit.set(unit)
    try:
        yield
        if unit.failed:
            raise RuntimeError("database work unit refused after a nested adapter failed")
    finally:
        unit.active = False
        _unit.reset(token)
