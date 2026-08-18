"""Workspace Control Plane Ports (CLOUD-WORKSPACE-CP-CON-01).

Provider-neutral seams between the domain contract and the successor
adapters: provisioning/snapshot/release orchestration, deterministic
uncertain reconciliation, and volume lifecycle. Implementations own
external systems; Core only owns the shapes below.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_core.domain.workspace_control import (
    MAX_NAMESPACE_LENGTH,
    SHA256_HEX_LENGTH,
    WorkspaceId,
    WorkspaceInstance,
    WorkspaceLifecycleState,
    WorkspaceSource,
)


class WorkspaceProvisionCommand(BaseModel):
    """Idempotent provisioning request submitted through the command lane."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: WorkspaceId
    deployment_namespace: str = Field(max_length=MAX_NAMESPACE_LENGTH)
    source: WorkspaceSource
    quota_bytes: int = Field(gt=0)
    owner_session_id: UUID | None = None
    idempotency_key: str = Field(min_length=1, max_length=255)

    @field_validator("deployment_namespace")
    @classmethod
    def require_namespace(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("provision namespace must be non-blank and trimmed")
        return value


class WorkspaceOperationReceipt(BaseModel):
    """Content-free proof that one lifecycle operation committed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: WorkspaceId
    operation_id: UUID
    resulting_state: WorkspaceLifecycleState
    idempotent_replay: bool = False


class WorkspaceSnapshotRef(BaseModel):
    """Durable snapshot pointer; bytes live in object storage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: UUID
    workspace_id: WorkspaceId
    materialized_revision: str = Field(min_length=1, max_length=255)
    content_digest: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)
    object_uri: str = Field(min_length=1, max_length=2048)

    @field_validator("content_digest")
    @classmethod
    def require_digest(cls, value: str) -> str:
        if not all(character in "0123456789abcdef" for character in value.lower()):
            raise ValueError("snapshot content digest must be a sha256 hex digest")
        return value


class WorkspaceProvisionerPort(Protocol):
    """Provision, snapshot, restore and release workspaces under leases.

    Implementations must be idempotent per ``idempotency_key``/operation id,
    must never re-execute an uncertain provision, and must resolve uncertain
    states deterministically through ``reconcile_uncertain``.
    """

    def provision(self, command: WorkspaceProvisionCommand) -> WorkspaceInstance: ...

    def snapshot(self, workspace_id: WorkspaceId) -> WorkspaceSnapshotRef: ...

    def restore(
        self,
        snapshot: WorkspaceSnapshotRef,
        *,
        deployment_namespace: str,
        quota_bytes: int,
        idempotency_key: str,
    ) -> WorkspaceInstance: ...

    def release(self, workspace_id: WorkspaceId) -> WorkspaceOperationReceipt: ...

    def reconcile_uncertain(
        self, *, deployment_namespace: str, limit: int = 100
    ) -> tuple[WorkspaceOperationReceipt, ...]: ...


class WorkspaceVolumePort(Protocol):
    """Deployment-owned volume lifecycle; volume refs are opaque strings."""

    def prepare(
        self,
        workspace_id: WorkspaceId,
        *,
        deployment_namespace: str,
        quota_bytes: int,
    ) -> str: ...

    def dispose(self, volume_ref: str) -> None: ...
