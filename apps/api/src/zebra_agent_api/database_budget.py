"""HTTP capacity lane selection; no authorization, retry or execution authority."""

import asyncio
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import BoundedSemaphore, Lock
from typing import Any

from agent_storage.postgres.async_dispatch import async_dispatch_scope, storage_call
from agent_storage.postgres.connection_capacity import (
    ConnectionBudget,
    DatabaseCapacityExceeded,
    Lane,
    capacity_for,
    capacity_lane,
    capacity_scope,
    current_lane,
)
from fastapi import FastAPI
from psycopg_pool import PoolTimeout, TooManyRequests
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_CONTROL = re.compile(r"/(tasks|sessions)/[^/]+/(cancel|stop|suspend)")


class DatabaseBudgetMiddleware:
    def __init__(
        self, app: ASGIApp, *, budget: ConnectionBudget, calls: "ApiDatabaseCalls | None" = None,
    ) -> None:
        self.app, self.budget, self.calls = app, budget, calls
        self._admissions = {
            "normal": BoundedSemaphore(budget.profile.normal + budget.profile.pool),
            "read": BoundedSemaphore(budget.profile.read),
            "control": BoundedSemaphore(budget.profile.control),
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method, path = scope["method"].upper(), scope["path"]
        if method == "GET" and path in {"/health", "/health/live", "/health/ready"}:
            await self.app(scope, receive, send)
            return
        lane: Lane = "read" if method in {"GET", "HEAD"} else "normal"
        if method == "POST" and _CONTROL.fullmatch(path):
            lane = "control"
        started = False
        admitted = self._admissions[lane].acquire(blocking=False)
        if not admitted:
            await JSONResponse({"error": {"code": "capacity_unavailable"}},
                               status_code=503)(scope, receive, send)
            return

        def release_admission() -> None:
            nonlocal admitted
            if admitted:
                admitted = False
                self._admissions[lane].release()

        async def observed(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                release_admission()
            await send(message)

        with (
            capacity_scope(self.budget), capacity_lane(lane),
            async_dispatch_scope(self.calls.call if self.calls is not None else None),
        ):
            try:
                await self.app(scope, receive, observed)
            except (DatabaseCapacityExceeded, PoolTimeout, TooManyRequests):
                if started:
                    raise  # Original stream/receipt recovery owns an interrupted response.
                await JSONResponse({"error": {"code": "capacity_unavailable"}},
                                   status_code=503)(scope, receive, send)
            finally:
                release_admission()


class ApiDatabaseExecutorSaturated(DatabaseCapacityExceeded):
    """The API lane rejected work before a database connection was attempted."""


class ApiDatabaseCalls:
    """Bounded sync work per lane; cancellation never frees a running Future's slot."""

    def __init__(self, budget: ConnectionBudget) -> None:
        self._lock, self._closed = Lock(), False
        limits = {"normal": budget.profile.normal + budget.profile.pool,
                  "read": budget.profile.read, "control": budget.profile.control}
        self._pools = {k: ThreadPoolExecutor(v, thread_name_prefix=f"api-{k}")
                       for k, v in limits.items()}
        self._slots = {k: BoundedSemaphore(v) for k, v in limits.items()}

    async def call[T](
        self, action: Callable[..., T], *args: Any, wait_for_read_slot: bool = False, **kwargs: Any
    ) -> T:
        def invoke() -> T:
            # Nested async storage remains owned by this running synchronous callback.
            with async_dispatch_scope(None):
                return action(*args, **kwargs)

        lane = current_lane()
        while True:
            with self._lock:
                if self._closed:
                    raise ApiDatabaseExecutorSaturated("API database executor closed")
                if self._slots[lane].acquire(blocking=False):
                    try:
                        future = self._pools[lane].submit(copy_context().run, invoke)
                    except BaseException:
                        self._slots[lane].release()
                        raise
                    break
            if lane != "read" or not wait_for_read_slot:
                raise ApiDatabaseExecutorSaturated("API database lane unavailable")
            # ponytail: only admitted Host reads wait here under the HTTP auth deadline.
            # A separate FIFO would be needed if this small waiter set required ordering.
            await asyncio.sleep(0.01)
        future.add_done_callback(lambda _: self._slots[lane].release())
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.shield(wrapped)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        for pool in self._pools.values():
            pool.shutdown(wait=True, cancel_futures=False)


async def database_call[T](
    app: FastAPI | None, action: Callable[..., T], *args: Any,
    wait_for_read_slot: bool = False, **kwargs: Any,
) -> T:
    calls: ApiDatabaseCalls | None = (
        getattr(getattr(app, "state", None), "database_calls", None)
    )
    if calls is None:
        return await storage_call(action, *args, **kwargs)
    return await calls.call(action, *args, wait_for_read_slot=wait_for_read_slot, **kwargs)


def configure_database_budget(app: FastAPI, health: Any, dsn: str) -> None:
    budget = capacity_for(dsn)
    if budget is None:
        return
    calls = ApiDatabaseCalls(budget)
    app.state.database_budget, app.state.database_calls = budget, calls
    health.capacity_close = calls.close
    app.add_middleware(DatabaseBudgetMiddleware, budget=budget, calls=calls)
