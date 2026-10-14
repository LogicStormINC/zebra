"""Borrowed Redis connections share the existing public output deadline."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from math import isfinite
from threading import RLock
from time import monotonic
from typing import Any, cast

from agent_core.harness.public_output_lifecycle import current_public_output_deadline
from redis.connection import Connection, SSLConnection, UnixDomainSocketConnection, parse_url
from redis.exceptions import TimeoutError as RedisTimeoutError

_REDIS_DEADLINE: ContextVar[float | None] = ContextVar("redis_io_deadline", default=None)


def current_redis_io_deadline() -> float | None:
    deadlines = [
        d for d in (_REDIS_DEADLINE.get(), current_public_output_deadline()) if d is not None
    ]
    return min(deadlines) if deadlines else None


@contextmanager
def redis_io_deadline(deadline: float) -> Iterator[None]:
    if type(deadline) not in (int, float) or not isfinite(deadline) or deadline <= monotonic():
        raise TimeoutError("Redis I/O deadline exceeded")
    parent = current_redis_io_deadline()
    token = _REDIS_DEADLINE.set(min(parent, deadline) if parent is not None else deadline)
    try:
        yield
    finally:
        _REDIS_DEADLINE.reset(token)


@contextmanager
def transient_lock(lock: RLock) -> Iterator[None]:
    deadline = current_redis_io_deadline()
    if deadline is None:
        lock.acquire()
    elif not lock.acquire(timeout=max(0, deadline - monotonic())):
        raise TimeoutError("temporary output lock deadline exceeded")
    try:
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError("temporary output deadline exceeded")
        yield
    finally:
        lock.release()


class _DeadlineRedisConnection:
    """Keep the installed Redis pool, but clip connect/send/read to one budget."""

    socket_connect_timeout: float | None
    socket_timeout: float | None
    _sock: Any

    def connect(self) -> None:
        original_connect, original_read = self.socket_connect_timeout, self.socket_timeout
        deadline = current_redis_io_deadline()
        if deadline is not None:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise RedisTimeoutError("temporary output connect deadline exceeded")
            self.socket_connect_timeout = min(original_connect or remaining, remaining)
            self.socket_timeout = min(original_read or remaining, remaining)
        try:
            cast(Any, super()).connect()
        finally:
            self.socket_connect_timeout, self.socket_timeout = original_connect, original_read

    def _clip_socket(self) -> None:
        deadline = current_redis_io_deadline()
        timeout = self.socket_timeout
        if deadline is not None:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise RedisTimeoutError("temporary output I/O deadline exceeded")
            timeout = min(timeout or remaining, remaining)
        # Redis exposes no per-command timeout. Each pool connection is exclusively
        # borrowed; its native socket is reset on every send/read, never pool-wide.
        if self._sock is not None:
            self._sock.settimeout(timeout)

    def send_packed_command(self, command: Any, check_health: bool = True) -> None:
        self._clip_socket()
        cast(Any, super()).send_packed_command(command, check_health=check_health)

    def read_response(self, *args: Any, **kwargs: Any) -> Any:
        self._clip_socket()
        return cast(Any, super()).read_response(*args, **kwargs)


class TransientRedisConnection(_DeadlineRedisConnection, Connection):
    """Deadline-clipped native TCP transport."""


class TransientSSLRedisConnection(TransientRedisConnection, SSLConnection):
    """Retain the installed dependency's TLS verification and handshake behavior."""


class TransientUnixRedisConnection(_DeadlineRedisConnection, UnixDomainSocketConnection):
    """Keep native Unix path construction and socket behavior under the same deadline."""


def deadline_redis_options(url: str) -> dict[str, Any]:
    options: dict[str, Any] = cast(Any, parse_url)(url)
    transport = options.get("connection_class", Connection)
    options["connection_class"] = {
        Connection: TransientRedisConnection,
        SSLConnection: TransientSSLRedisConnection,
        UnixDomainSocketConnection: TransientUnixRedisConnection,
    }[transport]
    return options
