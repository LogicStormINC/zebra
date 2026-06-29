from dataclasses import replace
from subprocess import TimeoutExpired, run

from agent_core.ports.runtime import (
    RuntimeCapabilityError,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
    RuntimeHandle,
    RuntimePort,
    RuntimeSnapshot,
)


def _normalize_output(output: bytes | str | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


class LocalRuntime(RuntimePort):
    def __init__(self) -> None:
        self._handles: dict[str, RuntimeHandle] = {}

    def execute(self, request: RuntimeExecutionRequest) -> RuntimeExecutionResult:
        try:
            completed = run(
                request.command,
                capture_output=True,
                text=True,
                cwd=request.cwd,
                env=dict(request.env) if request.env is not None else None,
                timeout=request.timeout_seconds,
                check=False,
            )
        except TimeoutExpired as exc:
            return RuntimeExecutionResult(
                command=request.command,
                exit_code=None,
                stdout=_normalize_output(exc.stdout),
                stderr=_normalize_output(exc.stderr),
                timed_out=True,
            )

        return RuntimeExecutionResult(
            command=request.command,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
        )

    def provision(self, *, workspace_root: str | None = None) -> RuntimeHandle:
        handle = RuntimeHandle.create(
            runtime_name="local",
            workspace_root=workspace_root,
        )
        self._handles[handle.handle_id] = handle
        return handle

    def snapshot(self, handle: RuntimeHandle) -> RuntimeSnapshot:
        self._require_known_handle(handle)
        raise RuntimeCapabilityError("local runtime does not support snapshot")

    def restore(self, snapshot: RuntimeSnapshot) -> RuntimeHandle:
        raise RuntimeCapabilityError("local runtime does not support restore")

    def fork(self, snapshot: RuntimeSnapshot) -> RuntimeHandle:
        raise RuntimeCapabilityError("local runtime does not support fork")

    def suspend(self, handle: RuntimeHandle) -> RuntimeHandle:
        current = self._require_known_handle(handle)
        if current.suspended:
            return current
        suspended = replace(current, suspended=True)
        self._handles[current.handle_id] = suspended
        return suspended

    def resume(self, handle: RuntimeHandle) -> RuntimeHandle:
        current = self._require_known_handle(handle)
        if not current.suspended:
            return current
        resumed = replace(current, suspended=False)
        self._handles[current.handle_id] = resumed
        return resumed

    def _require_known_handle(self, handle: RuntimeHandle) -> RuntimeHandle:
        current = self._handles.get(handle.handle_id)
        if current is None:
            raise RuntimeCapabilityError("runtime handle is unknown to local runtime")
        return current
