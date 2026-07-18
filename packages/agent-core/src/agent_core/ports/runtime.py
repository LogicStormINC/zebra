import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import uuid4


class RuntimeClass(StrEnum):
    TRUSTED_LOCAL = "trusted-local"
    OS_SANDBOX = "os-sandbox"
    OCI_ROOTLESS = "oci-rootless"
    GVISOR = "gvisor"


@dataclass(frozen=True)
class RuntimeLimits:
    cpu_count: float = 2.0
    memory_mb: int = 2048
    pids: int = 256
    tmpfs_mb: int = 512
    max_output_bytes: int = 1_048_576
    max_execution_seconds: float = 900.0
    workspace_quota_mb: int | None = None

    def __post_init__(self) -> None:
        if self.cpu_count <= 0:
            raise ValueError("cpu_count must be positive")
        for name in ("memory_mb", "pids", "tmpfs_mb", "max_output_bytes"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_execution_seconds <= 0:
            raise ValueError("max_execution_seconds must be positive")
        if self.workspace_quota_mb is not None and self.workspace_quota_mb <= 0:
            raise ValueError("workspace_quota_mb must be positive when provided")


@dataclass(frozen=True)
class SandboxSpec:
    runtime_class: RuntimeClass
    image: str
    workspace_root: str
    session_id: str = "local-session"
    attempt_number: int = 1
    engine: str = "docker"
    runtime_handler: str = "runsc"
    network_profile: str = "none"
    workspace_writable: bool = True
    container_uid: int = 65532
    container_gid: int = 65532
    limits: RuntimeLimits = RuntimeLimits()

    def __post_init__(self) -> None:
        if self.runtime_class in {
            RuntimeClass.OCI_ROOTLESS,
            RuntimeClass.GVISOR,
        } and not re.fullmatch(r".+@sha256:[0-9a-fA-F]{64}", self.image):
            raise ValueError("hard runtime image must be pinned by sha256 digest")
        if not self.workspace_root.strip():
            raise ValueError("workspace_root must not be blank")
        if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", self.session_id):
            raise ValueError("session_id is invalid for runtime identity")
        if self.attempt_number <= 0:
            raise ValueError("attempt_number must be positive")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", self.engine):
            raise ValueError("runtime engine is invalid")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", self.runtime_handler):
            raise ValueError("runtime handler is invalid")
        if self.network_profile not in {
            "none",
            "domain-allowlist",
            "mcp-proxy-only",
            "git-proxy-only",
        }:
            raise ValueError("network_profile is unsupported by hard runtime")
        if self.container_uid < 1 or self.container_gid < 1:
            raise ValueError("hard runtime container user must be non-root")

    @property
    def digest(self) -> str:
        payload = {
            "container_gid": self.container_gid,
            "container_uid": self.container_uid,
            "image": self.image,
            "engine": self.engine,
            "limits": {
                "cpu_count": self.limits.cpu_count,
                "max_execution_seconds": self.limits.max_execution_seconds,
                "max_output_bytes": self.limits.max_output_bytes,
                "memory_mb": self.limits.memory_mb,
                "pids": self.limits.pids,
                "tmpfs_mb": self.limits.tmpfs_mb,
                "workspace_quota_mb": self.limits.workspace_quota_mb,
            },
            "network_profile": self.network_profile,
            "runtime_class": self.runtime_class.value,
            "runtime_handler": self.runtime_handler,
            "session_id": self.session_id,
            "workspace_writable": self.workspace_writable,
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class RuntimeCapabilities:
    runtime_class: RuntimeClass
    available: bool
    engine: str
    engine_version: str | None = None
    enforcement: str = "unavailable"
    reason: str | None = None


@dataclass(frozen=True)
class EffectiveRuntimeAuthority:
    runtime_class: RuntimeClass
    engine: str
    image: str | None
    spec_digest: str
    network_enforcement: str
    workspace_writable: bool


@dataclass(frozen=True)
class RuntimeExecutionRequest:
    command: tuple[str, ...]
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("command must not be empty")
        if not self.command[0].strip():
            raise ValueError("command executable must not be blank")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True)
class RuntimeExecutionResult:
    command: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    failure_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return not self.timed_out and self.exit_code == 0


@dataclass(frozen=True)
class RuntimeHandle:
    handle_id: str
    runtime_name: str
    workspace_root: str | None = None
    suspended: bool = False
    authority: EffectiveRuntimeAuthority | None = None

    @classmethod
    def create(
        cls,
        *,
        runtime_name: str,
        workspace_root: str | None = None,
        suspended: bool = False,
        authority: EffectiveRuntimeAuthority | None = None,
    ) -> "RuntimeHandle":
        return cls(
            handle_id=str(uuid4()),
            runtime_name=runtime_name,
            workspace_root=workspace_root,
            suspended=suspended,
            authority=authority,
        )


@dataclass(frozen=True)
class RuntimeSnapshot:
    snapshot_id: str
    runtime_name: str
    source_handle_id: str
    created_at: datetime
    workspace_root: str | None = None
    snapshot_path: str | None = None
    authority_digest: str | None = None
    image: str | None = None

    @classmethod
    def create(
        cls,
        *,
        runtime_name: str,
        source_handle_id: str,
        created_at: datetime | None = None,
        workspace_root: str | None = None,
        snapshot_path: str | None = None,
        authority_digest: str | None = None,
        image: str | None = None,
    ) -> "RuntimeSnapshot":
        return cls(
            snapshot_id=str(uuid4()),
            runtime_name=runtime_name,
            source_handle_id=source_handle_id,
            created_at=created_at or datetime.now(UTC),
            workspace_root=workspace_root,
            snapshot_path=snapshot_path,
            authority_digest=authority_digest,
            image=image,
        )


class RuntimeSnapshotStatus(StrEnum):
    VALID = "valid"
    MISSING = "missing"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class RuntimeSnapshotInspection:
    snapshot_id: str
    snapshot_path: str | None
    status: RuntimeSnapshotStatus
    problems: tuple[str, ...] = ()

    @property
    def restorable(self) -> bool:
        return self.status is RuntimeSnapshotStatus.VALID


@dataclass(frozen=True)
class RuntimeSnapshotCleanupResult:
    snapshot_id: str
    snapshot_path: str | None
    status: RuntimeSnapshotStatus
    removed: bool
    problems: tuple[str, ...] = ()


class RuntimeCapabilityError(RuntimeError):
    """Raised when a runtime operation is unsupported or invalid."""


class RuntimePort(Protocol):
    def inspect_capabilities(self) -> RuntimeCapabilities: ...

    def execute(self, request: RuntimeExecutionRequest) -> RuntimeExecutionResult: ...

    def provision(
        self,
        *,
        workspace_root: str | None = None,
        spec: SandboxSpec | None = None,
    ) -> RuntimeHandle: ...

    def snapshot(self, handle: RuntimeHandle) -> RuntimeSnapshot: ...

    def inspect_snapshot(self, snapshot: RuntimeSnapshot) -> RuntimeSnapshotInspection: ...

    def cleanup_snapshot(self, snapshot: RuntimeSnapshot) -> RuntimeSnapshotCleanupResult: ...

    def restore(self, snapshot: RuntimeSnapshot) -> RuntimeHandle: ...

    def fork(self, snapshot: RuntimeSnapshot) -> RuntimeHandle: ...

    def suspend(self, handle: RuntimeHandle) -> RuntimeHandle: ...

    def resume(self, handle: RuntimeHandle) -> RuntimeHandle: ...

    def destroy(self, handle: RuntimeHandle) -> None: ...

    def destroy_session(self, session_id: str) -> int: ...
