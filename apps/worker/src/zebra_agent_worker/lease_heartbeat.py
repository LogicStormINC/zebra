from __future__ import annotations

from threading import Event, Lock, Thread
from types import TracebackType
from typing import Literal

from agent_core.domain.leases import WorkerLease

from zebra_agent_worker.claims import SessionClaimService


class LeaseHeartbeatError(RuntimeError):
    """Raised when background Lease maintenance can no longer prove ownership."""


class LeaseHeartbeat:
    def __init__(
        self,
        claim_service: SessionClaimService,
        lease: WorkerLease,
        *,
        lease_ttl_seconds: int,
    ) -> None:
        if lease_ttl_seconds <= 0:
            raise ValueError("lease ttl must be positive")
        self._claim_service = claim_service
        self._lease = lease
        self._lease_ttl_seconds = lease_ttl_seconds
        self._interval_seconds = lease_ttl_seconds / 3
        self._stop = Event()
        self._started = Event()
        self._lock = Lock()
        self._failure: BaseException | None = None
        self._thread = Thread(
            target=self._run,
            name=f"lease-heartbeat-{lease.session_id}",
            daemon=True,
        )

    def __enter__(self) -> LeaseHeartbeat:
        self._thread.start()
        self._started.wait()
        self.require_owned()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc_type, traceback
        self._stop.set()
        self._thread.join()
        failure = self._failure
        try:
            self._claim_service.release_lease(self._lease)
        except Exception as release_error:
            if exc is not None:
                exc.add_note(f"lease cleanup failed: {release_error}")
                return False
            if failure is not None:
                failure.add_note(f"lease cleanup failed: {release_error}")
            else:
                raise
        if exc is None and failure is not None:
            raise LeaseHeartbeatError("worker Lease heartbeat failed") from failure
        return False

    def require_owned(self) -> None:
        with self._lock:
            failure = self._failure
        if failure is not None:
            raise LeaseHeartbeatError("worker Lease ownership was lost") from failure

    def _run(self) -> None:
        self._started.set()
        while not self._stop.wait(self._interval_seconds):
            try:
                lease = self._claim_service.heartbeat_lease(
                    self._lease,
                    lease_ttl_seconds=self._lease_ttl_seconds,
                )
            except BaseException as error:
                with self._lock:
                    self._failure = error
                self._stop.set()
                return
            with self._lock:
                self._lease = lease
