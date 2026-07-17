from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired, run

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

EngineRunner = Callable[..., CompletedProcess[str]]
_KEEPALIVE_SCRIPT = "trap 'exit 0' TERM INT; while :; do sleep 3600; done"


class OciRuntime(RuntimePort):
    """Hardened, Docker-compatible OCI runtime with fail-closed preflight."""

    def __init__(
        self,
        spec: SandboxSpec,
        *,
        engine_command: Sequence[str] = ("docker",),
        gvisor_runtime: str = "runsc",
        snapshot_root: str | Path | None = None,
        runner: EngineRunner = run,
    ) -> None:
        if spec.runtime_class is RuntimeClass.TRUSTED_LOCAL:
            raise ValueError("OciRuntime requires an OCI or gVisor SandboxSpec")
        normalized_engine = tuple(part.strip() for part in engine_command if part.strip())
        if not normalized_engine:
            raise ValueError("engine_command must not be empty")
        if not gvisor_runtime.strip():
            raise ValueError("gvisor_runtime must not be blank")
        if " ".join(normalized_engine) != spec.engine:
            raise ValueError("engine command differs from SandboxSpec authority")
        if spec.runtime_class is RuntimeClass.GVISOR and gvisor_runtime != spec.runtime_handler:
            raise ValueError("gVisor handler differs from SandboxSpec authority")
        self._spec = spec
        self._engine = normalized_engine
        self._gvisor_runtime = gvisor_runtime.strip()
        self._runner = runner
        self._snapshots = LocalSnapshotBackend(root_path=snapshot_root)
        self._containers: dict[str, str] = {}
        self._handles: dict[str, RuntimeHandle] = {}
        self._active_handle_id: str | None = None

    @property
    def spec(self) -> SandboxSpec:
        return self._spec

    def inspect_capabilities(self) -> RuntimeCapabilities:
        version = self._invoke((*self._engine, "version", "--format", "{{.Server.Version}}"))
        if version.returncode != 0:
            return self._unavailable("OCI engine is unavailable")
        engine_version = version.stdout.strip() or None
        if self._spec.runtime_class is RuntimeClass.GVISOR:
            info = self._invoke((*self._engine, "info", "--format", "{{json .Runtimes}}"))
            try:
                runtimes = json.loads(info.stdout) if info.returncode == 0 else None
            except json.JSONDecodeError:
                runtimes = None
            if not isinstance(runtimes, dict) or self._gvisor_runtime not in runtimes:
                return self._unavailable(
                    f"OCI engine does not advertise runtime {self._gvisor_runtime}",
                    version=engine_version,
                )
            return RuntimeCapabilities(
                runtime_class=RuntimeClass.GVISOR,
                available=True,
                engine=" ".join(self._engine),
                engine_version=engine_version,
                enforcement=f"gvisor:{self._gvisor_runtime}",
            )
        rootless = self._invoke((*self._engine, "info", "--format", "{{.Host.Security.Rootless}}"))
        if rootless.returncode != 0 or rootless.stdout.strip().lower() != "true":
            return self._unavailable(
                "OCI engine did not prove rootless operation",
                version=engine_version,
            )
        return RuntimeCapabilities(
            runtime_class=RuntimeClass.OCI_ROOTLESS,
            available=True,
            engine=" ".join(self._engine),
            engine_version=engine_version,
            enforcement="rootless-user-namespace",
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
            raise RuntimeCapabilityError(capabilities.reason or "hard runtime is unavailable")
        self.destroy_session(effective_spec.session_id)
        authority = EffectiveRuntimeAuthority(
            runtime_class=effective_spec.runtime_class,
            engine=capabilities.engine,
            image=effective_spec.image,
            spec_digest=effective_spec.digest,
            network_enforcement="container-network-none",
            workspace_writable=effective_spec.workspace_writable,
        )
        handle = RuntimeHandle.create(
            runtime_name=effective_spec.runtime_class.value,
            workspace_root=str(root),
            authority=authority,
        )
        container_name = f"zebra-{handle.handle_id}"
        created = self._invoke(self._create_command(container_name, root, effective_spec))
        if created.returncode != 0:
            raise RuntimeCapabilityError(self._engine_failure("container create", created))
        container_id = created.stdout.strip()
        if not container_id:
            self._invoke((*self._engine, "rm", "--force", container_name))
            raise RuntimeCapabilityError("OCI engine returned an empty container id")
        started = self._invoke((*self._engine, "start", container_id))
        if started.returncode != 0:
            self._invoke((*self._engine, "rm", "--force", container_id))
            raise RuntimeCapabilityError(self._engine_failure("container start", started))
        if effective_spec.workspace_writable:
            writable = self._invoke(
                (
                    *self._engine,
                    "exec",
                    container_id,
                    "/bin/sh",
                    "-c",
                    "test -w /workspace",
                ),
                timeout=10,
            )
            if writable.returncode != 0:
                self._invoke((*self._engine, "rm", "--force", container_id))
                raise RuntimeCapabilityError(
                    "hard runtime container user cannot write the workspace"
                )
        self._containers[handle.handle_id] = container_id
        self._handles[handle.handle_id] = handle
        self._active_handle_id = handle.handle_id
        return handle

    def execute(self, request: RuntimeExecutionRequest) -> RuntimeExecutionResult:
        if request.env:
            raise RuntimeCapabilityError(
                "hard runtime does not accept per-command environment variables"
            )
        handle = self._active_handle()
        container_id = self._containers[handle.handle_id]
        cwd = self._container_cwd(request.cwd, handle)
        timeout = min(
            request.timeout_seconds or self._spec.limits.max_execution_seconds,
            self._spec.limits.max_execution_seconds,
        )
        command = (
            *self._engine,
            "exec",
            "--workdir",
            cwd,
            container_id,
            *request.command,
        )
        try:
            completed = self._invoke(command, timeout=timeout)
        except TimeoutExpired as exc:
            self.destroy(handle)
            stdout, stdout_truncated = self._bounded_output(exc.stdout)
            stderr, stderr_truncated = self._bounded_output(exc.stderr)
            return RuntimeExecutionResult(
                command=request.command,
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
            )
        stdout, stdout_truncated = self._bounded_output(completed.stdout)
        stderr, stderr_truncated = self._bounded_output(completed.stderr)
        return RuntimeExecutionResult(
            command=request.command,
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
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
        if current.suspended:
            return current
        completed = self._invoke((*self._engine, "pause", self._containers[current.handle_id]))
        if completed.returncode != 0:
            raise RuntimeCapabilityError(self._engine_failure("container pause", completed))
        suspended = replace(current, suspended=True)
        self._handles[current.handle_id] = suspended
        return suspended

    def resume(self, handle: RuntimeHandle) -> RuntimeHandle:
        current = self._require_handle(handle)
        if not current.suspended:
            return current
        completed = self._invoke((*self._engine, "unpause", self._containers[current.handle_id]))
        if completed.returncode != 0:
            raise RuntimeCapabilityError(self._engine_failure("container unpause", completed))
        resumed = replace(current, suspended=False)
        self._handles[current.handle_id] = resumed
        return resumed

    def destroy(self, handle: RuntimeHandle) -> None:
        current = self._handles.pop(handle.handle_id, None)
        container_id = self._containers.pop(handle.handle_id, None)
        if current is None or container_id is None:
            return
        removed = self._invoke((*self._engine, "rm", "--force", "--volumes", container_id))
        if self._active_handle_id == handle.handle_id:
            self._active_handle_id = None
        if removed.returncode != 0:
            raise RuntimeCapabilityError(self._engine_failure("container cleanup", removed))

    def destroy_session(self, session_id: str) -> int:
        listed = self._invoke(
            (
                *self._engine,
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"label=zebra.agent.session={session_id}",
            )
        )
        if listed.returncode != 0:
            raise RuntimeCapabilityError(self._engine_failure("container list", listed))
        container_ids = tuple(line.strip() for line in listed.stdout.splitlines() if line.strip())
        for container_id in container_ids:
            removed = self._invoke((*self._engine, "rm", "--force", "--volumes", container_id))
            if removed.returncode != 0:
                raise RuntimeCapabilityError(self._engine_failure("container cleanup", removed))
        return len(container_ids)

    def close(self) -> None:
        for handle in tuple(self._handles.values()):
            self.destroy(handle)

    def _create_command(
        self,
        container_name: str,
        workspace_root: Path,
        spec: SandboxSpec,
    ) -> tuple[str, ...]:
        bind_mount = f"type=bind,source={workspace_root},target=/workspace"
        if not spec.workspace_writable:
            bind_mount += ",readonly"
        command = [
            *self._engine,
            "create",
            "--name",
            container_name,
            "--label",
            "zebra.agent.runtime=1",
            "--label",
            f"zebra.agent.session={spec.session_id}",
            "--label",
            f"zebra.agent.spec={spec.digest}",
            "--label",
            f"zebra.agent.attempt={spec.attempt_number}",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(spec.limits.pids),
            "--memory",
            f"{spec.limits.memory_mb}m",
            "--cpus",
            str(spec.limits.cpu_count),
            "--user",
            f"{spec.container_uid}:{spec.container_gid}",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={spec.limits.tmpfs_mb}m",
            "--mount",
            bind_mount,
            "--workdir",
            "/workspace",
        ]
        if spec.runtime_class is RuntimeClass.GVISOR:
            command.extend(("--runtime", self._gvisor_runtime))
        command.extend(("--entrypoint", "/bin/sh", spec.image, "-c", _KEEPALIVE_SCRIPT))
        return tuple(command)

    def _active_handle(self) -> RuntimeHandle:
        if self._active_handle_id is None:
            return self.provision()
        return self._handles[self._active_handle_id]

    def _require_handle(self, handle: RuntimeHandle) -> RuntimeHandle:
        current = self._handles.get(handle.handle_id)
        if current is None:
            raise RuntimeCapabilityError("runtime handle is unknown to OCI runtime")
        return current

    def _require_snapshot_authority(self, snapshot: RuntimeSnapshot) -> None:
        if snapshot.runtime_name != self._spec.runtime_class.value:
            raise RuntimeCapabilityError("snapshot runtime class does not match configured runtime")
        if snapshot.authority_digest != self._spec.digest or snapshot.image != self._spec.image:
            raise RuntimeCapabilityError("snapshot authority differs from configured runtime")

    def _container_cwd(self, cwd: str | None, handle: RuntimeHandle) -> str:
        workspace = self._workspace_root(handle.workspace_root)
        target = self._workspace_root(cwd or str(workspace))
        try:
            relative = target.relative_to(workspace)
        except ValueError as exc:
            raise RuntimeCapabilityError("runtime cwd must stay within workspace") from exc
        return "/workspace" if not relative.parts else f"/workspace/{relative.as_posix()}"

    @staticmethod
    def _workspace_root(value: str | None) -> Path:
        if value is None or not value.strip():
            raise RuntimeCapabilityError("hard runtime requires workspace_root")
        root = Path(value).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise RuntimeCapabilityError("hard runtime workspace_root must be a directory")
        return root

    def _bounded_output(self, value: bytes | str | None) -> tuple[str, bool]:
        if value is None:
            return "", False
        encoded = value if isinstance(value, bytes) else value.encode("utf-8", errors="replace")
        limit = self._spec.limits.max_output_bytes
        truncated = len(encoded) > limit
        return encoded[:limit].decode("utf-8", errors="replace"), truncated

    def _invoke(
        self,
        command: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> CompletedProcess[str]:
        return self._runner(
            tuple(command),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    def _unavailable(self, reason: str, *, version: str | None = None) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            runtime_class=self._spec.runtime_class,
            available=False,
            engine=" ".join(self._engine),
            engine_version=version,
            reason=reason,
        )

    @staticmethod
    def _engine_failure(operation: str, completed: CompletedProcess[str]) -> str:
        detail = (completed.stderr or completed.stdout).strip()[:2048]
        return f"OCI {operation} failed" + (f": {detail}" if detail else "")
