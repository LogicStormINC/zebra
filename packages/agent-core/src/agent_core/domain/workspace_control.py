"""Provider-neutral Cloud Workspace Control Plane domain.

Freezes the P0.3 contract from ``CLOUD-WORKSPACE-CP-PLAN-01``: workspace
sources, lifecycle instances and the pure transition table. Storage,
provisioning adapters and API composition live in successor cards; this
module deliberately imports nothing outside ``agent_core.domain``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NewType
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WorkspaceId = NewType("WorkspaceId", UUID)

MAX_LOCATOR_LENGTH = 2_048
MAX_NAMESPACE_LENGTH = 255
MAX_VOLUME_REF_LENGTH = 1_024
SHA256_HEX_LENGTH = 64


class WorkspaceSourceKind(StrEnum):
    GIT_REPOSITORY = "git_repository"
    UPLOADED_ARCHIVE = "uploaded_archive"
    DURABLE_SNAPSHOT = "durable_snapshot"
    HOST_REFERENCE = "host_reference"


class WorkspaceLifecycleState(StrEnum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    READY = "ready"
    SEALED = "sealed"
    RELEASED = "released"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class WorkspaceAction(StrEnum):
    PROVISION_START = "provision_start"
    PROVISION_SUCCEED = "provision_succeed"
    PROVISION_FAIL = "provision_fail"
    PROVISION_MARK_UNCERTAIN = "provision_mark_uncertain"
    UNCERTAIN_RESOLVE_SUCCEED = "uncertain_resolve_succeed"
    UNCERTAIN_RESOLVE_FAIL = "uncertain_resolve_fail"
    SEAL = "seal"
    SNAPSHOT = "snapshot"
    RELEASE = "release"


_TRANSITIONS: dict[WorkspaceLifecycleState, frozenset[WorkspaceAction]] = {
    WorkspaceLifecycleState.PENDING: frozenset(
        {WorkspaceAction.PROVISION_START, WorkspaceAction.RELEASE}
    ),
    WorkspaceLifecycleState.PROVISIONING: frozenset(
        {
            WorkspaceAction.PROVISION_SUCCEED,
            WorkspaceAction.PROVISION_FAIL,
            WorkspaceAction.PROVISION_MARK_UNCERTAIN,
        }
    ),
    WorkspaceLifecycleState.READY: frozenset(
        {WorkspaceAction.SEAL, WorkspaceAction.SNAPSHOT, WorkspaceAction.RELEASE}
    ),
    WorkspaceLifecycleState.SEALED: frozenset({WorkspaceAction.SNAPSHOT, WorkspaceAction.RELEASE}),
    WorkspaceLifecycleState.RELEASED: frozenset(),
    WorkspaceLifecycleState.FAILED: frozenset({WorkspaceAction.RELEASE}),
    WorkspaceLifecycleState.UNCERTAIN: frozenset(
        {
            WorkspaceAction.UNCERTAIN_RESOLVE_SUCCEED,
            WorkspaceAction.UNCERTAIN_RESOLVE_FAIL,
        }
    ),
}

_ACTION_TARGETS: dict[WorkspaceAction, WorkspaceLifecycleState] = {
    WorkspaceAction.PROVISION_START: WorkspaceLifecycleState.PROVISIONING,
    WorkspaceAction.PROVISION_SUCCEED: WorkspaceLifecycleState.READY,
    WorkspaceAction.PROVISION_FAIL: WorkspaceLifecycleState.FAILED,
    WorkspaceAction.PROVISION_MARK_UNCERTAIN: WorkspaceLifecycleState.UNCERTAIN,
    WorkspaceAction.UNCERTAIN_RESOLVE_SUCCEED: WorkspaceLifecycleState.READY,
    WorkspaceAction.UNCERTAIN_RESOLVE_FAIL: WorkspaceLifecycleState.FAILED,
    WorkspaceAction.SEAL: WorkspaceLifecycleState.SEALED,
    WorkspaceAction.SNAPSHOT: WorkspaceLifecycleState.READY,
    WorkspaceAction.RELEASE: WorkspaceLifecycleState.RELEASED,
}


class WorkspaceTransitionError(ValueError):
    """Raised when a lifecycle action is illegal for the current state."""


class WorkspaceSource(BaseModel):
    """Immutable materialization input; bytes live in object storage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: WorkspaceSourceKind
    locator: str = Field(max_length=MAX_LOCATOR_LENGTH)
    pinned_revision: str | None = Field(default=None, max_length=255)
    content_digest: str | None = Field(default=None, max_length=SHA256_HEX_LENGTH)
    archive_artifact_uri: str | None = Field(default=None, max_length=MAX_LOCATOR_LENGTH)

    @field_validator("locator")
    @classmethod
    def require_locator(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("workspace source locator must be non-blank and trimmed")
        return value

    @field_validator("pinned_revision")
    @classmethod
    def require_revision(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("workspace pinned revision must be non-blank and trimmed")
        return value

    @field_validator("content_digest")
    @classmethod
    def require_digest(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != SHA256_HEX_LENGTH or not _is_hex(value)):
            raise ValueError("workspace content digest must be a sha256 hex digest")
        return value

    @model_validator(mode="after")
    def require_kind_pairing(self) -> WorkspaceSource:
        if self.kind is WorkspaceSourceKind.GIT_REPOSITORY:
            if self.pinned_revision is None:
                raise ValueError("git repository sources must pin a revision")
        elif self.pinned_revision is not None:
            raise ValueError("pinned revision is only valid for git repository sources")
        if self.kind is WorkspaceSourceKind.UPLOADED_ARCHIVE:
            if self.archive_artifact_uri is None:
                raise ValueError("uploaded archive sources must reference their artifact uri")
        elif self.archive_artifact_uri is not None:
            raise ValueError("archive artifact uri is only valid for uploaded archives")
        return self


class WorkspaceInstance(BaseModel):
    """Authoritative workspace record; PostgreSQL owns it in the successor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: WorkspaceId
    deployment_namespace: str = Field(max_length=MAX_NAMESPACE_LENGTH)
    source: WorkspaceSource
    state: WorkspaceLifecycleState
    materialized_revision: str | None = Field(default=None, max_length=255)
    content_digest: str | None = Field(default=None, max_length=SHA256_HEX_LENGTH)
    volume_ref: str | None = Field(default=None, max_length=MAX_VOLUME_REF_LENGTH)
    owner_session_id: UUID | None = None
    quota_bytes: int = Field(gt=0)
    provision_operation_id: UUID | None = None

    @field_validator("deployment_namespace")
    @classmethod
    def require_namespace(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("workspace deployment namespace must be non-blank and trimmed")
        return value

    @field_validator("content_digest")
    @classmethod
    def require_digest(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != SHA256_HEX_LENGTH or not _is_hex(value)):
            raise ValueError("workspace content digest must be a sha256 hex digest")
        return value

    @model_validator(mode="after")
    def require_ready_facts(self) -> WorkspaceInstance:
        if self.state in {WorkspaceLifecycleState.READY, WorkspaceLifecycleState.SEALED}:
            if not self.materialized_revision or not self.content_digest:
                raise ValueError("ready workspaces must carry revision and content digest")
        return self


def _is_hex(value: str) -> bool:
    return all(character in "0123456789abcdef" for character in value.lower())


def next_workspace_state(
    current: WorkspaceLifecycleState,
    action: WorkspaceAction,
) -> WorkspaceLifecycleState:
    """Pure lifecycle table; adapters must not invent transitions."""
    allowed = _TRANSITIONS.get(current, frozenset())
    if action not in allowed:
        raise WorkspaceTransitionError(
            f"workspace action {action.value} is illegal in state {current.value}"
        )
    return _ACTION_TARGETS[action]


def workspace_actions_for(state: WorkspaceLifecycleState) -> frozenset[WorkspaceAction]:
    return _TRANSITIONS.get(state, frozenset())
