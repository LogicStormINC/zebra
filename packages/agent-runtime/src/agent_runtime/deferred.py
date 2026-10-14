"""One attempt's lazy runtime; no fake handle, global cache or retry."""

from collections.abc import Callable
from threading import RLock

from agent_core.ports.runtime import (
    RuntimeCapabilities,
    RuntimeCapabilityError,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
    RuntimeHandle,
    RuntimePort,
    RuntimeSnapshot,
    RuntimeSnapshotCleanupResult,
    RuntimeSnapshotInspection,
    SandboxSpec,
)


class DeferredRuntime:
    def __init__(
        self,
        prepare: Callable[[], tuple[RuntimePort, RuntimeHandle]],
        *,
        ready: Callable[[RuntimeHandle], None] | None = None,
        check: Callable[[], None] | None = None,
    ) -> None:
        self._prepare, self._ready = prepare, ready
        self._check = check or (lambda: None)
        self._lock = RLock()
        self._runtime: RuntimePort | None = None
        self._handle: RuntimeHandle | None = None
        self._failure: BaseException | None = None
        self._closed = False
        self._preparing = False
        self._cleanup_failure: Exception | None = None

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("deferred runtime is closed")

    def ensure_ready(self) -> RuntimeHandle:
        with self._lock:
            self._require_open()
            if self._failure is not None:
                raise self._failure
            if self._preparing:
                raise RuntimeError("deferred runtime preparation is already in progress")
            self._check()
            self._require_open()
            if self._handle is not None:
                return self._handle
            self._preparing = True
            try:
                self._runtime, self._handle = self._prepare()
                self._require_open()
                self._check()
                self._require_open()
                if self._ready is not None:
                    self._ready(self._handle)
                    self._require_open()
                self._check()
                self._require_open()
                return self._handle
            except BaseException as error:
                self._failure = error
                try:
                    self._destroy_ready()
                except Exception as cleanup:
                    error.add_note(f"runtime cleanup failed: {type(cleanup).__name__}")
                raise
            finally:
                self._preparing = False

    def _destroy_ready(self) -> None:
        handle, self._handle = self._handle, None
        if self._runtime is not None and handle is not None:
            try:
                self._runtime.destroy(handle)
            except Exception as error:
                self._cleanup_failure = error
                raise

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._destroy_ready()
            if self._cleanup_failure is not None:
                raise self._cleanup_failure

    def _prepared_runtime(self) -> RuntimePort:
        self.ensure_ready()
        assert self._runtime is not None
        return self._runtime

    def inspect_capabilities(self) -> RuntimeCapabilities:
        return self._prepared_runtime().inspect_capabilities()

    def execute(self, request: RuntimeExecutionRequest) -> RuntimeExecutionResult:
        return self._prepared_runtime().execute(request)

    def provision(
        self, *, workspace_root: str | None = None, spec: SandboxSpec | None = None
    ) -> RuntimeHandle:
        if workspace_root is not None or spec is not None:
            raise RuntimeCapabilityError("deferred runtime does not accept provision overrides")
        return self.ensure_ready()

    def _require_handle(self, handle: RuntimeHandle) -> RuntimePort:
        if self._handle is None or handle != self._handle:
            raise RuntimeCapabilityError("runtime handle differs from this attempt")
        return self._prepared_runtime()

    def snapshot(self, handle: RuntimeHandle) -> RuntimeSnapshot:
        return self._require_handle(handle).snapshot(handle)

    def inspect_snapshot(self, snapshot: RuntimeSnapshot) -> RuntimeSnapshotInspection:
        return self._prepared_runtime().inspect_snapshot(snapshot)

    def cleanup_snapshot(self, snapshot: RuntimeSnapshot) -> RuntimeSnapshotCleanupResult:
        return self._prepared_runtime().cleanup_snapshot(snapshot)

    def restore(self, snapshot: RuntimeSnapshot) -> RuntimeHandle:
        raise RuntimeCapabilityError("snapshot restore requires eager runtime composition")

    def fork(self, snapshot: RuntimeSnapshot) -> RuntimeHandle:
        raise RuntimeCapabilityError("snapshot fork requires eager runtime composition")

    def suspend(self, handle: RuntimeHandle) -> RuntimeHandle:
        with self._lock:
            self._handle = self._require_handle(handle).suspend(handle)
            return self._handle

    def resume(self, handle: RuntimeHandle) -> RuntimeHandle:
        with self._lock:
            self._handle = self._require_handle(handle).resume(handle)
            return self._handle

    def destroy(self, handle: RuntimeHandle) -> None:
        with self._lock:
            if self._handle is None or handle != self._handle:
                raise RuntimeCapabilityError("runtime handle differs from this attempt")
            self.close()

    def destroy_session(self, session_id: str) -> int:
        raise RuntimeCapabilityError("deferred runtime does not support session-wide destruction")
