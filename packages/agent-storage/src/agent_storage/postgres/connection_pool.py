"""Explicit process-lifetime Cloud pool; never changes bounded Task I/O."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from psycopg import Connection
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_POOL: ContextVar[
    tuple[dict[str, str | int | None], ConnectionPool[Connection[dict[str, Any]]]] | None
] = (
    ContextVar("postgres_composition_pool", default=None)
)


def composition_pool(dsn: str) -> ConnectionPool[Connection[dict[str, Any]]] | None:
    binding = _POOL.get()
    return binding[1] if binding and binding[0] == conninfo_to_dict(dsn) else None


@contextmanager
def postgres_pool_scope(dsn: str) -> Iterator[None]:
    # Captured by adapters during composition, including adapters used in Worker
    # threads. No global DSN registry or pool shared across unrelated processes.
    with ConnectionPool[Connection[dict[str, Any]]](
        dsn, min_size=1, max_size=8, timeout=2, max_waiting=32,
        kwargs={"row_factory": dict_row, "connect_timeout": 2},
        check=ConnectionPool.check_connection,
    ) as pool:
        token = _POOL.set((conninfo_to_dict(dsn), pool))
        try:
            yield
        finally:
            _POOL.reset(token)
