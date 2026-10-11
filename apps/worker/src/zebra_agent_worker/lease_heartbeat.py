from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from threading import Event, Lock, Thread
from time import monotonic
from types import TracebackType
from typing import Literal

from agent_core.domain.leases import WorkerLease
from agent_storage.leases import SQLiteLeaseStore

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
        release_on_exit: bool = True,
    ) -> None:
        if lease_ttl_seconds <= 0:
            raise ValueError("lease ttl must be positive")
        self._claim_service = claim_service
        self._lease = lease
        self._lease_ttl_seconds = lease_ttl_seconds
        self._release_on_exit = release_on_exit
        # SQLite keeps its existing local I/O behavior; remote Ports share the native PG budget.
        self._bounded_io = not isinstance(
            getattr(claim_service, "_lease_store", None), SQLiteLeaseStore
        )
        self._io_seconds = min(2.0, lease_ttl_seconds / 3)
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
        if not self._started.wait(self._io_seconds if self._bounded_io else None):
            self._stop.set()
            raise LeaseHeartbeatError("worker Lease heartbeat did not start")
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
        deadline = monotonic() + self._io_seconds + 0.2 if self._bounded_io else None
        self._thread.join(None if deadline is None else max(0, deadline - monotonic()))
        if self._thread.is_alive():
            error = LeaseHeartbeatError("worker Lease heartbeat did not stop within its I/O budget")
            if exc is not None:
                exc.add_note(str(error))
                return False
            raise error
        failure = self._failure
        try:
            if self._release_on_exit:
                self._call(lambda: self._claim_service.release_lease(self._lease), deadline)
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
        with self._locked():
            failure = self._failure
        if failure is not None:
            raise LeaseHeartbeatError("worker Lease ownership was lost") from failure
        if self._stop.is_set():
            raise LeaseHeartbeatError("worker Lease heartbeat has stopped")

    def advance_checkpoint(self, checkpoint: int) -> WorkerLease:
        """Serialize renewals so the background thread cannot submit an older checkpoint."""
        return self._renew(checkpoint)

    @contextmanager
    def _locked(self) -> Iterator[float | None]:
        deadline = monotonic() + self._io_seconds if self._bounded_io else None
        if deadline is not None:
            from agent_storage.postgres.task_io import current_task_io_deadline

            if (outer := current_task_io_deadline()) is not None:
                deadline = min(deadline, outer)
        acquired = (
            self._lock.acquire()
            if deadline is None
            else self._lock.acquire(timeout=max(0, deadline - monotonic()))
        )
        if not acquired:
            self._stop.set()
            raise LeaseHeartbeatError("worker Lease heartbeat lock deadline exceeded")
        try:
            yield deadline
        finally:
            self._lock.release()

    @staticmethod
    def _io_scope(deadline: float | None) -> AbstractContextManager[None]:
        if deadline is None:
            return nullcontext()
        from agent_storage.postgres.task_io import task_io_deadline

        return task_io_deadline(deadline)

    def _call[T](self, operation: Callable[[], T], deadline: float | None) -> T:
        if deadline is None:
            return operation()
        from psycopg.errors import LockNotAvailable

        with self._io_scope(deadline):
            while True:
                try:
                    return operation()
                except LockNotAvailable:
                    # Native lock_timeout confirms rollback, not an unknown COMMIT.
                    # Recovery Pages hold this fence too; retry only within the
                    # original cumulative budget, never a new lease/generation.
                    if monotonic() >= deadline:
                        raise

    def _renew(self, checkpoint: int | None = None, *, background: bool = False) -> WorkerLease:
        with self._locked() as deadline:
            if self._failure is not None:
                raise LeaseHeartbeatError("worker Lease ownership was lost") from self._failure
            if self._stop.is_set():
                if background:
                    return self._lease
                raise LeaseHeartbeatError("worker Lease heartbeat has stopped")
            try:
                self._lease = self._call(
                    lambda: self._claim_service.heartbeat_lease(
                        self._lease,
                        lease_ttl_seconds=self._lease_ttl_seconds,
                        checkpoint=checkpoint,
                    ),
                    deadline,
                )
            except BaseException as error:
                # Publish failure before releasing the lock: require_owned must
                # not slip between a failed DB renewal and its background report.
                self._failure = error
                self._stop.set()
                raise
            return self._lease

    def _run(self) -> None:
        self._started.set()
        while not self._stop.wait(self._interval_seconds):
            try:
                self._renew(background=True)
            except BaseException as error:
                self._failure = error
                self._stop.set()
                return
