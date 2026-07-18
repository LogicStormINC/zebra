from __future__ import annotations

import platform
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from shutil import which
from subprocess import CompletedProcess, TimeoutExpired

from agent_core.ports.runtime import (
    EffectiveRuntimeAuthority,
    RuntimeCapabilities,
    RuntimeCapabilityError,
    RuntimeClass,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
    RuntimeHandle,
    RuntimePort,
    RuntimeSnapshot,
    SandboxSpec,
)

from agent_runtime.adapters.local_snapshot_state import (
    LocalSnapshotCleanupResult,
    LocalSnapshotInspection,
)
from agent_runtime.adapters.local_snapshots import LocalSnapshotBackend
from agent_runtime.adapters.os_sandbox_platform import (
    build_execution_command,
    build_probe_command,
    os_sandbox_engine,
)
from agent_runtime.process_execution import run_process_tree
from agent_runtime.runtime_failures import normalize_runtime_failure

Runner = Callable[..., CompletedProcess[str]]
ExecutableFinder = Callable[[str], str | None]
_SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


class OsSandboxRuntime(RuntimePort):
    """Native OS sandbox that refuses execution when its boundary is unavailable."""

    def __init__(
        self,
        spec: SandboxSpec,
        *,
        snapshot_root: str | Path | None = None,
        system: str | None = None,
        finder: ExecutableFinder = which,
        runner: Runner = run_process_tree,
    ) -> None:
        if spec.runtime_class is not RuntimeClass.OS_SANDBOX:
            raise ValueError("OsSandboxRuntime requires an os-sandbox SandboxSpec")
        self._system = system or platform.system()
        expected_engine = os_sandbox_engine(self._system)
        if spec.engine != expected_engine:
            raise ValueError("OS sandbox engine differs from SandboxSpec authority")
        self._spec = spec
        self._executable = finder(expected_engine)
        self._runner = runner
        self._snapshots = LocalSnapshotBackend(root_path=snapshot_root)
        self._handles: dict[str, RuntimeHandle] = {}
        self._active_handle_id: str | None = None

    @property
    def spec(self) -> SandboxSpec:
        return self._spec

    def inspect_capabilities(self) -> RuntimeCapabilities:
        if self._executable is None:
            return self._unavailable(f"required OS sandbox engine {self._spec.engine} is missing")
        probe = self._probe_command()
        completed = self._invoke(probe, timeout=10)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[:512]
            reason = "OS sandbox capability probe failed" + (f": {detail}" if detail else "")
            return self._unavailable(reason)
        return RuntimeCapabilities(
            runtime_class=RuntimeClass.OS_SANDBOX,
            available=True,
            engine=self._executable,
            engine_version=platform.release(),
            enforcement="seatbelt" if self._system == "Darwin" else "bubblewrap-namespaces",
        )

    def provision(
        self,
        *,
        workspace_root: str | None = None,
        spec: SandboxSpec | None = None,
    ) -> RuntimeHandle:
        effective_spec = spec or self._spec
        if effective_spec.digest != self._spec.digest:
            raise RuntimeCapabilityError("runtime spec differs from configured authority")
        root = self._workspace_root(workspace_root or effective_spec.workspace_root)
        capabilities = self.inspect_capabilities()
        if not capabilities.available:
            raise RuntimeCapabilityError(capabilities.reason or "OS sandbox is unavailable")
        authority = EffectiveRuntimeAuthority(
            runtime_class=RuntimeClass.OS_SANDBOX,
            engine=capabilities.engine,
            image=None,
            spec_digest=effective_spec.digest,
            network_enforcement="os-sandbox-network-deny",
            workspace_writable=effective_spec.workspace_writable,
        )
        handle = RuntimeHandle.create(
            runtime_name=RuntimeClass.OS_SANDBOX.value,
            workspace_root=str(root),
            authority=authority,
        )
        self._handles[handle.handle_id] = handle
        self._active_handle_id = handle.handle_id
        return handle

    def execute(self, request: RuntimeExecutionRequest) -> RuntimeExecutionResult:
        if request.env:
            raise RuntimeCapabilityError(
                "OS sandbox does not accept per-command environment variables"
            )
        handle = self._active_handle()
        workspace = self._workspace_root(handle.workspace_root)
        cwd = self._sandbox_cwd(request.cwd, workspace)
        timeout = min(
            request.timeout_seconds or self._spec.limits.max_execution_seconds,
            self._spec.limits.max_execution_seconds,
        )
        assert self._executable is not None
        command = build_execution_command(
            system=self._system,
            executable=self._executable,
            command=request.command,
            workspace=workspace,
            cwd=cwd,
            workspace_writable=self._spec.workspace_writable,
        )
        try:
            completed = self._invoke(command, timeout=timeout, cwd=cwd)
        except TimeoutExpired as exc:
            return RuntimeExecutionResult(
                command=request.command,
                exit_code=None,
                stdout=self._output(exc.stdout),
                stderr=self._output(exc.stderr),
                timed_out=True,
                failure_reason="timeout",
            )
        return RuntimeExecutionResult(
            command=request.command,
            exit_code=completed.returncode,
            stdout=self._output(completed.stdout),
            stderr=self._output(completed.stderr),
            timed_out=False,
            failure_reason=normalize_runtime_failure(
                timed_out=False,
                exit_code=completed.returncode,
                stderr=self._output(completed.stderr),
            ),
        )

    def snapshot(self, handle: RuntimeHandle) -> RuntimeSnapshot:
        return self._snapshots.create_snapshot(self._require_handle(handle))

    def inspect_snapshot(self, snapshot: RuntimeSnapshot) -> LocalSnapshotInspection:
        self._require_snapshot_authority(snapshot)
        return self._snapshots.inspect_snapshot(snapshot)

    def cleanup_snapshot(self, snapshot: RuntimeSnapshot) -> LocalSnapshotCleanupResult:
        self._require_snapshot_authority(snapshot)
        return self._snapshots.cleanup_snapshot(snapshot)

    def restore(self, snapshot: RuntimeSnapshot) -> RuntimeHandle:
        self._require_snapshot_authority(snapshot)
        restored = self._snapshots.restore_handle(snapshot)
        return self.provision(workspace_root=restored.workspace_root)

    def fork(self, snapshot: RuntimeSnapshot) -> RuntimeHandle:
        self._require_snapshot_authority(snapshot)
        forked = self._snapshots.fork_handle(snapshot)
        return self.provision(workspace_root=forked.workspace_root)

    def suspend(self, handle: RuntimeHandle) -> RuntimeHandle:
        current = self._require_handle(handle)
        suspended = current if current.suspended else replace(current, suspended=True)
        self._handles[current.handle_id] = suspended
        return suspended

    def resume(self, handle: RuntimeHandle) -> RuntimeHandle:
        current = self._require_handle(handle)
        resumed = current if not current.suspended else replace(current, suspended=False)
        self._handles[current.handle_id] = resumed
        return resumed

    def destroy(self, handle: RuntimeHandle) -> None:
        self._handles.pop(handle.handle_id, None)
        if self._active_handle_id == handle.handle_id:
            self._active_handle_id = None

    def destroy_session(self, session_id: str) -> int:
        del session_id
        return 0

    def _active_handle(self) -> RuntimeHandle:
        if self._active_handle_id is None:
            return self.provision()
        return self._handles[self._active_handle_id]

    def _probe_command(self) -> tuple[str, ...]:
        assert self._executable is not None
        return build_probe_command(system=self._system, executable=self._executable)

    def _require_handle(self, handle: RuntimeHandle) -> RuntimeHandle:
        current = self._handles.get(handle.handle_id)
        if current is None:
            raise RuntimeCapabilityError("runtime handle is unknown to OS sandbox")
        return current

    def _require_snapshot_authority(self, snapshot: RuntimeSnapshot) -> None:
        if snapshot.runtime_name != RuntimeClass.OS_SANDBOX.value:
            raise RuntimeCapabilityError("snapshot runtime class does not match configured runtime")
        if snapshot.authority_digest != self._spec.digest or snapshot.image is not None:
            raise RuntimeCapabilityError("snapshot authority differs from configured runtime")

    @staticmethod
    def _workspace_root(value: str | None) -> Path:
        if value is None or not value.strip():
            raise RuntimeCapabilityError("OS sandbox requires workspace_root")
        root = Path(value).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise RuntimeCapabilityError("OS sandbox workspace_root must be a directory")
        return root

    @classmethod
    def _sandbox_cwd(cls, value: str | None, workspace: Path) -> Path:
        target = cls._workspace_root(value or str(workspace))
        try:
            target.relative_to(workspace)
        except ValueError as exc:
            raise RuntimeCapabilityError("runtime cwd must stay within workspace") from exc
        return target

    def _invoke(
        self,
        command: Sequence[str],
        *,
        timeout: float | None = None,
        cwd: Path | None = None,
    ) -> CompletedProcess[str]:
        return self._runner(
            tuple(command),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            cwd=cwd,
            env={"PATH": _SAFE_PATH},
        )

    def _unavailable(self, reason: str) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            runtime_class=RuntimeClass.OS_SANDBOX,
            available=False,
            engine=self._executable or self._spec.engine,
            reason=reason,
        )

    @staticmethod
    def _output(value: bytes | str | None) -> str:
        if value is None:
            return ""
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
