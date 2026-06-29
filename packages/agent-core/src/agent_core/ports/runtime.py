from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4


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

    @property
    def succeeded(self) -> bool:
        return not self.timed_out and self.exit_code == 0


@dataclass(frozen=True)
class RuntimeHandle:
    handle_id: str
    runtime_name: str
    workspace_root: str | None = None
    suspended: bool = False

    @classmethod
    def create(
        cls,
        *,
        runtime_name: str,
        workspace_root: str | None = None,
        suspended: bool = False,
    ) -> "RuntimeHandle":
        return cls(
            handle_id=str(uuid4()),
            runtime_name=runtime_name,
            workspace_root=workspace_root,
            suspended=suspended,
        )


@dataclass(frozen=True)
class RuntimeSnapshot:
    snapshot_id: str
    runtime_name: str
    source_handle_id: str
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        runtime_name: str,
        source_handle_id: str,
        created_at: datetime | None = None,
    ) -> "RuntimeSnapshot":
        return cls(
            snapshot_id=str(uuid4()),
            runtime_name=runtime_name,
            source_handle_id=source_handle_id,
            created_at=created_at or datetime.now(UTC),
        )


class RuntimeCapabilityError(RuntimeError):
    """Raised when a runtime operation is unsupported or invalid."""


class RuntimePort(Protocol):
    def execute(self, request: RuntimeExecutionRequest) -> RuntimeExecutionResult: ...

    def provision(self, *, workspace_root: str | None = None) -> RuntimeHandle: ...

    def snapshot(self, handle: RuntimeHandle) -> RuntimeSnapshot: ...

    def restore(self, snapshot: RuntimeSnapshot) -> RuntimeHandle: ...

    def fork(self, snapshot: RuntimeSnapshot) -> RuntimeHandle: ...

    def suspend(self, handle: RuntimeHandle) -> RuntimeHandle: ...

    def resume(self, handle: RuntimeHandle) -> RuntimeHandle: ...
