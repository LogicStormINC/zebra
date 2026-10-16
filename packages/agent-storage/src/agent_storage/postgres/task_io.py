"""Opt-in Task I/O budget: DNS process, libpq waits, queries and transaction exit.

Ordinary adapters inherit an explicit request scope; outside it they are unchanged.
No thread timeout pretends to cancel
DNS: a stalled resolver is killed and reaped. Resolved hosts retain their names
for TLS/password lookup; connection attempts share the same monotonic deadline.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from collections.abc import Generator, Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from threading import Lock
from time import monotonic
from types import TracebackType
from typing import Any, cast

import psycopg
from psycopg import ClientCursor, pq, waiting
from psycopg._conninfo_attempts import conninfo_attempts
from psycopg._conninfo_utils import get_param, is_ip_address, split_attempts
from psycopg.abc import RV, ConnDict, PQGen
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_TASK_IO_DEADLINE: ContextVar[float | None] = ContextVar("task_io_deadline", default=None)


def current_task_io_deadline() -> float | None:
    """Expose the current opt-in budget to existing database adapters."""
    return _TASK_IO_DEADLINE.get()


@contextmanager
def task_io_deadline(deadline: float) -> Iterator[None]:
    """Share one request budget across independent reads without changing Ports."""
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ValueError("Task storage deadline must be finite")
    current = _TASK_IO_DEADLINE.get()
    deadline = min(deadline, current) if current is not None else deadline
    _remaining(deadline)
    token = _TASK_IO_DEADLINE.set(deadline)
    try:
        yield
        _remaining(deadline)
    finally:
        _TASK_IO_DEADLINE.reset(token)


RESOLVE_HOST_SCRIPT = """import _socket as socket,sys
for item in socket.getaddrinfo(sys.argv[1].encode("ascii"),sys.argv[2],
                               proto=socket.IPPROTO_TCP,type=socket.SOCK_STREAM):
    print(item[4][0])
"""

RESOLVE_SCRIPT = """import json,sys
params=json.load(sys.stdin)
from psycopg import pq
from psycopg._conninfo_attempts import conninfo_attempts
from psycopg._conninfo_utils import get_param
from psycopg.conninfo import make_conninfo
if get_param(params,"service"):
    # libpq owns service/LDAP/environment precedence; keep any blocking lookup
    # in this killable child. No polling, authentication or SQL is performed.
    probe=pq.PGconn.connect_start(make_conninfo("",**params).encode())
    try:
        if probe.status == pq.ConnStatus.BAD:
            raise RuntimeError("service configuration could not be resolved")
        expanded={item.keyword.decode():item.val.decode()
                  for item in probe.info if item.val is not None}
    finally:
        probe.finish()
    params={**expanded,**params}
    params.pop("service",None)
json.dump(conninfo_attempts(params),sys.stdout)
"""


def _remaining(deadline: float) -> float:
    value = deadline - monotonic()
    if value <= 0:
        raise TimeoutError("Task storage operation deadline exceeded")
    return value


def _budgeted[Y, S, R](
    gen: Generator[Y, S, R],
    deadline: float,
) -> Generator[Y, S, R]:
    try:
        _remaining(deadline)
        state = next(gen)
        while True:
            ready = yield state
            _remaining(deadline)
            state = gen.send(ready)
    except StopIteration as finished:
        return finished.value  # type: ignore[no-any-return]
    finally:
        if sys.exc_info()[0] is None:
            gen.close()
        else:
            with suppress(Exception):
                gen.close()


class TaskIoConnection(psycopg.Connection[dict[str, Any]]):
    deadline: float
    operation_deadline: float

    def wait(self, gen: PQGen[RV], interval: float = 0.01) -> RV:
        try:
            return waiting.wait(
                _budgeted(gen, self.operation_deadline),
                self.pgconn.socket,
                interval=min(interval, 0.01),
            )
        except BaseException as exc:
            if (
                isinstance(exc, psycopg.Error)
                and exc.sqlstate is not None
                and not self.closed
                and self.pgconn.status == pq.ConnStatus.OK
                and self.pgconn.transaction_status
                in {
                    pq.TransactionStatus.IDLE,
                    pq.TransactionStatus.INTRANS,
                    pq.TransactionStatus.INERROR,
                }
                and monotonic() < self.operation_deadline
            ):
                # Native ErrorResponse is complete, not a lost/unknown reply.
                # A confirmed statement cancellation can roll back its savepoint
                # within the same remaining budget, preserving a derived prefix.
                raise
            # A COMMIT outcome can be unknown. Callers reconcile, never replay a
            # canonical write merely because this bounded connection disappeared.
            if not self.closed and pq.version() >= 170000:
                with suppress(Exception):
                    if self.pgconn.transaction_status == pq.TransactionStatus.ACTIVE:
                        waiting.wait_conn(
                            _budgeted(
                                self._cancel_gen(timeout=_remaining(self.deadline)), self.deadline
                            ),
                            interval=0.01,
                        )
            with suppress(Exception):
                self.close()
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        except BaseException:
            with suppress(Exception):
                self.close()
            if exc_val is not None:
                raise exc_val.with_traceback(exc_tb) from None
            raise
        else:
            if exc_val is None:
                self.close()  # Base Connection skips close when COMMIT raises.
            else:
                with suppress(Exception):
                    self.close()


class TaskIoConnections:
    """Shared addresses; optional existing callback scope owns short-lived sockets."""

    def __init__(self, dsn: str) -> None:
        self._params = conninfo_to_dict(dsn)
        self._attempts: tuple[ConnDict, ...] = ()
        self._resolved_at = 0.0
        self._environment: tuple[tuple[str, str], ...] = ()
        self._lock = Lock()

    def require_compatible(self, dsn: str) -> None:
        """Do not share resolved addresses across different connection settings."""
        if conninfo_to_dict(dsn) != self._params:
            raise ValueError("Task I/O connector connection configuration does not match")

    def _resolve(self, deadline: float) -> tuple[ConnDict, ...]:
        if not self._lock.acquire(timeout=_remaining(deadline)):
            raise TimeoutError("Task storage resolver admission deadline exceeded")
        try:
            environment = os.environ.copy()
            signature = tuple(
                sorted(
                    (key, value)
                    for key, value in environment.items()
                    if key.startswith("PG") or key == "HOME"
                )
            )
            service = bool(get_param(self._params, "service"))
            # ponytail: service files may change outside this process. Never cache
            # expanded service settings; inspect them in the bounded child each
            # time. Only direct-DSN addresses use the shared thirty-second cache.
            if (
                not service
                and self._attempts
                and signature == self._environment
                and monotonic() - self._resolved_at < 30
            ):
                return tuple({**self._params, **address} for address in self._attempts)
            needs_dns = service or any(
                (host := get_param(attempt, "host"))
                and not host.startswith("/")
                and host[1:2] != ":"
                and not get_param(attempt, "hostaddr")
                and not is_ip_address(host)
                for attempt in split_attempts(self._params)
            )
            if not needs_dns:
                attempts = conninfo_attempts(self._params)
            else:
                # ponytail: native libc DNS has no cancellation contract. One
                # short child per DSN/30s bounds it; no per-query process or new
                # dependency. DNS cache invalidates after all addresses fail.
                direct_host = str(self._params.get("host") or "")
                direct_port = str(self._params.get("port") or "")
                direct = (
                    bool(direct_host)
                    and direct_host.isascii()
                    and "," not in direct_host
                    and direct_port.isdigit()
                    and not service
                    and self._params.get(
                        "target_session_attrs", environment.get("PGTARGETSESSIONATTRS")
                    )
                    != "prefer-standby"
                    and self._params.get(
                        "load_balance_hosts", environment.get("PGLOADBALANCEHOSTS")
                    )
                    != "random"
                )
                # ponytail: ASCII names need no IDNA codec or JSON/site imports
                # in the killable child. Keep settings/credentials in the parent;
                # international names and complex settings stay with libpq.
                command = (
                    [sys.executable, "-S", "-c", RESOLVE_HOST_SCRIPT, direct_host, direct_port]
                    if direct
                    else [sys.executable, "-c", RESOLVE_SCRIPT]
                )
                with subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    env=environment,
                ) as child:
                    try:
                        output, _ = child.communicate(
                            None if direct else json.dumps(self._params),
                            timeout=_remaining(deadline),
                        )
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.communicate()
                        raise TimeoutError("Task storage DNS deadline exceeded") from None
                    if child.returncode:
                        raise psycopg.OperationalError("Task storage hostname resolution failed")
                attempts = (
                    [{**self._params, "hostaddr": address} for address in output.splitlines()]
                    if direct
                    else json.loads(output)
                )
            _remaining(deadline)
            self._attempts = (
                ()
                if service
                else tuple(
                    {
                        key: value
                        for key, value in attempt.items()
                        if key in {"host", "hostaddr", "port"}
                    }
                    for attempt in attempts
                )
            )
            self._environment, self._resolved_at = signature, monotonic()
            return tuple(attempts)
        finally:
            self._lock.release()

    def connect(
        self,
        *,
        timeout_seconds: float = 2,
        deadline: float | None = None,
        client_cursor: bool = False,
    ) -> TaskIoConnection:
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 2
        ):
            raise ValueError("Task storage I/O budget must be finite and within two seconds")
        if deadline is not None and (
            type(deadline) not in (int, float) or not math.isfinite(deadline)
        ):
            raise ValueError("Task storage deadline must be finite")
        now = monotonic()
        deadline = (
            min(deadline, now + timeout_seconds) if deadline is not None else now + timeout_seconds
        )
        if (scoped := _TASK_IO_DEADLINE.get()) is not None:
            deadline = min(deadline, scoped)
        operation_deadline = deadline - min(0.2, _remaining(deadline) * 0.1)
        from agent_storage.postgres.connection_scope import current_connection_scope

        scope = current_connection_scope()
        if (
            scope is not None and (scope.bounded_deadline is not None or scope.task_io_only)
            and scoped is not None
            and pq.version() >= 170000 and not get_param(self._params, "service")
        ):
            environment = tuple(sorted(
                (key, value) for key, value in os.environ.items()
                if key.startswith("PG") or key == "HOME"
            ))
            # ponytail: reuse the existing synchronous scope, never a global pool.
            # Native libpq cancellation bounds later borrows' shorter remaining budget.
            # Older clients keep fresh server timeouts; ordinary sockets never share keys.
            key = (
                "task-io", make_conninfo("", **self._params), client_cursor, environment,
                None if scope.task_io_only else scoped,
            )
            connection = scope.borrow(
                key, lambda: self._open(deadline, operation_deadline, client_cursor)
            )
            check_idle = scope.task_io_only and connection.deadline != deadline
            connection.deadline, connection.operation_deadline = deadline, operation_deadline
            if check_idle:
                try:
                    # Empty protocol query, once at the next callback. Renew the
                    # native budget first; no application statement has been sent.
                    ConnectionPool.check_connection(connection)
                except psycopg.OperationalError:
                    connection.close()
                    connection = scope.borrow(
                        key, lambda: self._open(deadline, operation_deadline, client_cursor)
                    )
            connection.prepare_threshold = None  # DISCARD ALL removes server plans.
            return cast(TaskIoConnection, connection)
        return self._open(deadline, operation_deadline, client_cursor)

    def _open(
        self, deadline: float, operation_deadline: float, client_cursor: bool
    ) -> TaskIoConnection:
        attempts = self._resolve(operation_deadline)
        failure: psycopg.Error | None = None
        for attempt in attempts:
            milliseconds = max(1, int(_remaining(operation_deadline) * 1000))
            options = str(attempt.get("options") or "") + (
                f" -c statement_timeout={milliseconds} -c lock_timeout={min(50, milliseconds)}"
            )
            try:
                connection = waiting.wait_conn(
                    _budgeted(
                        TaskIoConnection._connect_gen(
                            make_conninfo("", **{**attempt, "options": options})
                        ),
                        operation_deadline,
                    ),
                    interval=0.01,
                )
            except psycopg.Error as exc:
                failure = exc
                continue
            except TimeoutError:
                self._attempts = ()
                raise
            connection.deadline, connection.operation_deadline = deadline, operation_deadline
            connection.row_factory = dict_row
            if client_cursor:
                connection.cursor_factory = ClientCursor
            return connection
        self._attempts = ()
        if failure is not None:
            raise failure
        raise psycopg.OperationalError("Task storage has no connection addresses")
