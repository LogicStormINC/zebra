"""Process health and aged control-plane observations; never execution authority."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any

from agent_storage import PostgresControlPlaneStores
from agent_storage.postgres.epoch import read_control_plane_epoch
from agent_storage.postgres.task_io import task_io_deadline
from fastapi import FastAPI
from fastapi.responses import JSONResponse


class ApiHealth:
    def __init__(
        self,
        api: Any = None,
        authorizer: Any = None,
        *,
        check: Callable[[], bool] | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.api, self.authorizer = api, authorizer
        self.check = check if check is not None else self._control_plane_available
        self.clock = clock
        self.thread: Thread | None = None
        self.sampled = Event()
        self._stop, self._lock = Event(), Lock()
        self._checked_at: float | None = None
        self._available = False

    def _control_plane_available(self) -> bool:
        # Schema compatibility is already checked by the existing Cloud factory.
        # Probe only the common control-plane dependency, not optional tools/models.
        if self.api.settings.deployment == "local":
            return True
        stores = self.api.stores
        if not isinstance(stores, PostgresControlPlaneStores):
            return False
        with task_io_deadline(monotonic() + 0.75):
            read_control_plane_epoch(
                self.api.settings.database_url, deployment_namespace=stores.deployment_namespace
            )
        return True

    def sample_once(self) -> None:
        if self._stop.is_set():
            return
        try:
            available = self.check()
        except Exception:
            available = False
        with self._lock:
            if not self._stop.is_set():
                self._available, self._checked_at = available, self.clock()
                self.sampled.set()

    def status(self) -> str:
        with self._lock:
            ready = (
                not self._stop.is_set()
                and self._available
                and self._checked_at is not None
                and 0 <= self.clock() - self._checked_at <= 5
            )
        return "ready" if ready else "not_ready"

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self.thread is not None or self._stop.is_set():
                raise RuntimeError("health observation lifecycle already started or closed")
            self.thread = Thread(target=self._run, name="api-health", daemon=True)
            self.thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.sample_once()
            self._stop.wait(1)

    def close(self) -> None:
        self._stop.set()
        if self.thread is not None:
            # Default probe uses the existing bounded DNS/socket/query/exit budget.
            self.thread.join(2)
            if self.thread.is_alive():
                raise RuntimeError("health probe exceeded its shutdown budget")

    def register(self, app: FastAPI) -> None:
        app.state.health = self

        async def live() -> JSONResponse:
            return JSONResponse({"status": "alive"}, headers={"Cache-Control": "no-store"})

        async def ready() -> JSONResponse:
            status = self.status()
            return JSONResponse(
                {"status": status},
                status_code=200 if status == "ready" else 503,
                headers={"Cache-Control": "no-store"},
            )

        # Exact GET routes precede the authenticated catch-all. No prefix exemptions.
        app.add_api_route("/health/live", live, methods=["GET"])
        app.add_api_route("/health/ready", ready, methods=["GET"])

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI) -> AsyncIterator[None]:
        try:
            if self.api.settings.deployment != "local":
                from zebra_agent_api.host_auth import warm_host_grant_keys

                await warm_host_grant_keys(self.authorizer)
            self.start()
            yield
        finally:
            try:
                self.close()
            finally:
                if self.api.stream_v2_reader is not None:
                    await self.api.stream_v2_reader.close()
                if self.api.stream_notifications is not None:
                    await self.api.stream_notifications.close()
