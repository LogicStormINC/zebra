"""Callback-local sockets, never shared transactions or cached query results."""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import get_ident
from typing import Any

_scope: ContextVar["ConnectionScope | None"] = ContextVar("postgres_connections", default=None)
_logger = logging.getLogger(__name__)


class ConnectionScope:
    def __init__(self) -> None:
        self.thread = get_ident()
        self.closed = False
        self.idle: dict[tuple[str, str], list[Any]] = {}
        self.connections: list[Any] = []

    def borrow(self, key: tuple[str, str], create: Callable[[], Any]) -> Any:
        available = self.idle.setdefault(key, [])
        while available and available[-1].closed:
            self.discard(available.pop())
        connection = available.pop() if available else create()
        if connection not in self.connections:
            self.connections.append(connection)
        return _Borrow(self, key, connection)

    def discard(self, connection: Any) -> None:
        try:
            connection.close()
        finally:
            if connection in self.connections:
                self.connections.remove(connection)

    def release(self, key: tuple[str, str], connection: Any, failed: bool) -> None:
        try:
            if failed:
                connection.rollback()
            else:
                connection.commit()
        except BaseException:
            self.discard(connection)
            raise
        try:
            # Match a fresh connection, including temporary/session state. Disable
            # automatic prepares when opening sockets: DISCARD removes server plans.
            connection.autocommit = True
            connection.execute("DISCARD ALL")
            connection.autocommit = False
            connection.isolation_level = None
            connection.read_only = None
            connection.deferrable = None
        except Exception:
            self.discard(connection)
            _logger.warning("Discarded callback database connection after reset failure")
            return
        # ponytail: at most eight idle sockets per callback; no global pool or
        # cross-thread sharing. A process-wide pool needs explicit lifecycle wiring.
        if self.closed or sum(map(len, self.idle.values())) >= 8:
            self.discard(connection)
        else:
            self.idle[key].append(connection)

    def close(self) -> None:
        self.closed = True
        for connection in self.connections:
            connection.close()
        self.idle.clear()
        self.connections.clear()


class _Borrow:
    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"owner", "key", "connection", "released"}:
            object.__setattr__(self, name, value)
        else:
            if self.released:
                raise RuntimeError("database connection borrow has ended")
            setattr(self.connection, name, value)

    def __init__(self, owner: ConnectionScope, key: tuple[str, str], connection: Any) -> None:
        self.owner, self.key, self.connection = owner, key, connection
        self.released = False

    def __getattr__(self, name: str) -> Any:
        if self.released:
            raise RuntimeError("database connection borrow has ended")
        return getattr(self.connection, name)

    def __enter__(self) -> "_Borrow":
        if self.released:
            raise RuntimeError("database connection borrow has ended")
        return self

    def __exit__(self, kind: Any, error: Any, traceback: Any) -> None:
        if not self.released:
            self.released = True
            self.owner.release(self.key, self.connection, kind is not None)

    def close(self) -> None:
        if not self.released:
            self.released = True
            self.owner.discard(self.connection)


def current_connection_scope() -> ConnectionScope | None:
    scope = _scope.get()
    return scope if scope is not None and not scope.closed and scope.thread == get_ident() else None


@contextmanager
def postgres_connection_scope() -> Iterator[None]:
    """Only explicit synchronous callback composition opts into physical reuse."""
    if current_connection_scope() is not None:
        yield
        return
    scope = ConnectionScope()
    token = _scope.set(scope)
    try:
        yield
    finally:
        _scope.reset(token)
        scope.close()
