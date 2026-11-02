"""Explicit process-lifetime Cloud pool; never changes bounded Task I/O."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import Context, ContextVar
from typing import Any

from psycopg import Connection
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from agent_storage.postgres.capacity_profile import CapacityProfile
from agent_storage.postgres.connection_capacity import (
    PROFILE_ENV,
    ConnectionBudget,
    capacity_context,
    capacity_root_active,
    capacity_scope,
    connect,
)

_POOL: ContextVar[
    tuple[dict[str, str | int | None], ConnectionPool[Connection[dict[str, Any]]]] | None
] = (
    ContextVar("postgres_composition_pool", default=None)
)


def composition_pool(dsn: str) -> ConnectionPool[Connection[dict[str, Any]]] | None:
    binding = _POOL.get()
    return binding[1] if binding and binding[0] == conninfo_to_dict(dsn) else None


def _reset_transaction_defaults(connection: Connection[dict[str, Any]]) -> None:
    # The pool ends the borrower's transaction first, but retains these client
    # defaults. Reset before reuse; psycopg_pool discards a connection on failure.
    # No SQL: readonly snapshots remain readonly until their transaction ends.
    connection.autocommit = False
    connection.isolation_level = None
    connection.read_only = None
    connection.deferrable = None


@contextmanager
def postgres_pool_scope(
    dsn: str, *, component: str = "worker", execution_slots: int | None = None,
) -> Iterator[ConnectionBudget | None]:
    # Captured by adapters during composition, including adapters used in Worker
    # threads. No global DSN registry or pool shared across unrelated processes.
    profile = (CapacityProfile.parse(os.environ[PROFILE_ENV])
               if os.environ.get(PROFILE_ENV) else None)
    if profile is not None and capacity_root_active():
        raise ValueError("database process budget is already composed")
    budget = ConnectionBudget(dsn, profile, component) if profile is not None else None
    if profile is not None and execution_slots is not None:
        if execution_slots > profile.execution_slots:
            raise ValueError("Worker execution slots exceed frozen database inventory")
    with capacity_scope(budget):
        try:
            if budget is not None:
                with connect(dsn, budget=budget, lane="control", row_factory=dict_row,
                             connect_timeout=2, options="-c statement_timeout=1500") as check:
                    row = check.execute(
                        "SELECT current_setting('max_connections')::int AS maximum, "
                        "current_setting('superuser_reserved_connections')::int + "
                        "COALESCE(current_setting('reserved_connections',true),'0')::int "
                        "AS reserved, "
                        "(SELECT rolsuper FROM pg_roles WHERE rolname=current_user) AS superuser"
                    ).fetchone()
                    assert row is not None
                    budget.profile.require_server(row)
            with ConnectionPool[Connection[dict[str, Any]]](
                dsn, min_size=1, max_size=profile.pool if profile else 8, timeout=2, max_waiting=32,
                kwargs={"row_factory": dict_row, "connect_timeout": 2},
                check=ConnectionPool.check_connection,
                reset=_reset_transaction_defaults,
            ) as pool:
                token = _POOL.set((conninfo_to_dict(dsn), pool))
                try:
                    yield budget
                finally:
                    _POOL.reset(token)
        finally:
            if budget is not None:
                budget.close()


def postgres_context() -> Context:
    context = capacity_context()
    context.run(_POOL.set, _POOL.get())
    return context
