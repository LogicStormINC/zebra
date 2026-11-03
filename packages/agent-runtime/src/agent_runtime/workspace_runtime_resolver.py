"""Resolve workspace:// references into materialized runtime roots.

The Worker's runtime seam (CLOUD-WORKSPACE-CP-RT-01): plain paths pass
through unchanged for the local profile; control-plane bound references
resolve through the provisioner with fail-closed semantics and revision
fencing for continuations.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from agent_core.domain.workspace_control import (
    WorkspaceId,
    WorkspaceInstance,
    WorkspaceLifecycleState,
    WorkspaceSourceKind,
)

from agent_runtime.workspace_provisioner import PostgresWorkspaceProvisioner

WORKSPACE_URI_PREFIX = "workspace://"


class WorkspaceRuntimeResolutionError(ValueError):
    """Raised when a bound workspace cannot be resolved fail-closed."""


class WorkspaceRuntimeResolver:
    def __init__(
        self,
        provisioner: PostgresWorkspaceProvisioner,
        *,
        prepare_volume: Callable[[WorkspaceId, UUID], None] | None = None,
        verify_volume: Callable[[WorkspaceId, UUID, Path], None] | None = None,
    ) -> None:
        self._provisioner = provisioner
        self._prepare_volume, self._verify_volume = prepare_volume, verify_volume

    def planned_host_root(self, workspace_ref: str, *, session_id: UUID) -> Path | None:
        """Read the exact mount target, never create or assert readiness."""
        if not _is_workspace_reference(workspace_ref):
            return None
        instance = self._provisioner.store.get(_workspace_id(workspace_ref))
        if instance is None:
            raise WorkspaceRuntimeResolutionError("workspace is unknown to the control plane")
        return self._host_root(instance, session_id)

    def _host_root(self, instance: WorkspaceInstance, session_id: UUID) -> Path | None:
        if instance.source.kind is not WorkspaceSourceKind.HOST_REFERENCE:
            return None
        if instance.owner_session_id != session_id:
            raise WorkspaceRuntimeResolutionError("workspace belongs to a different Session")
        if instance.state is WorkspaceLifecycleState.PENDING:
            root = self._provisioner._volume_path(instance.workspace_id)
        elif instance.state is WorkspaceLifecycleState.READY and instance.volume_ref:
            root = Path(instance.volume_ref)
        else:
            return None
        if not root.is_absolute() or root.resolve(strict=False) != root:
            raise WorkspaceRuntimeResolutionError("workspace volume path must be canonical")
        return root

    def resolve(
        self, workspace_ref: str, *, session_id: UUID, expected_host_root: Path | None = None,
        check: Callable[[], None] | None = None,
    ) -> Path:
        if not _is_workspace_reference(workspace_ref):
            if expected_host_root is not None:
                raise WorkspaceRuntimeResolutionError("deferred workspace lost its reference")
            return Path(workspace_ref)
        workspace_id = _workspace_id(workspace_ref)
        instance = self._provisioner.store.get(workspace_id)
        if instance is None:
            raise WorkspaceRuntimeResolutionError(
                f"workspace {workspace_ref} is unknown to the control plane"
            )
        if expected_host_root is not None and (
            check is None or self._host_root(instance, session_id) != expected_host_root
        ):
            raise WorkspaceRuntimeResolutionError("deferred workspace target or fence changed")
        if check is not None:
            check()
        if self._prepare_volume is not None:
            self._prepare_volume(workspace_id, session_id)
        if check is not None:
            check()
        instance = self._provisioner.provision_existing(workspace_id)
        root = self._require_materialized(workspace_ref, instance)
        if (
            expected_host_root is not None
            and self._host_root(instance, session_id) != expected_host_root
        ):
            raise WorkspaceRuntimeResolutionError("workspace mount target changed")
        if check is not None:
            check()
        if self._verify_volume is not None:
            self._verify_volume(workspace_id, session_id, root)
        if check is not None:
            check()
        return root

    def resolve_ready(self, workspace_ref: str, *, session_id: UUID) -> Path:
        """Continuation path: never provisions, only verifies fenced facts."""
        if not _is_workspace_reference(workspace_ref):
            return Path(workspace_ref)
        store = self._provisioner.store
        instance = store.get(_workspace_id(workspace_ref))
        if instance is None:
            raise WorkspaceRuntimeResolutionError(
                f"workspace {workspace_ref} is unknown to the control plane"
            )
        root = self._require_materialized(workspace_ref, instance)
        if self._verify_volume is not None:
            self._verify_volume(instance.workspace_id, session_id, root)
        return root

    def verify_revision(self, workspace_ref: str, *, materialized_revision: str) -> None:
        if not _is_workspace_reference(workspace_ref):
            return
        instance = self._provisioner.store.get(_workspace_id(workspace_ref))
        if instance is None or instance.materialized_revision != materialized_revision:
            raise WorkspaceRuntimeResolutionError(
                f"workspace {workspace_ref} drifted from revision {materialized_revision}"
            )

    def _require_materialized(self, workspace_ref: str, instance: object) -> Path:
        state = getattr(instance, "state", None)
        volume_ref = getattr(instance, "volume_ref", None)
        if (
            state
            not in {
                WorkspaceLifecycleState.READY,
                WorkspaceLifecycleState.SEALED,
            }
            or not volume_ref
        ):
            state_name = getattr(state, "value", state)
            raise WorkspaceRuntimeResolutionError(
                f"workspace {workspace_ref} is not materialized (state={state_name})"
            )
        root = Path(str(volume_ref))
        if not root.is_dir():
            raise WorkspaceRuntimeResolutionError(
                f"workspace {workspace_ref} volume {volume_ref} is missing"
            )
        return root


def _is_workspace_reference(workspace_ref: str) -> bool:
    """Path() folds the double slash, so both spellings must be accepted."""
    return workspace_ref.startswith(WORKSPACE_URI_PREFIX) or workspace_ref.startswith("workspace:/")


def _workspace_id(workspace_ref: str) -> WorkspaceId:
    raw = workspace_ref.removeprefix(WORKSPACE_URI_PREFIX).removeprefix("workspace:/")
    try:
        return WorkspaceId(UUID(raw))
    except ValueError as error:
        raise WorkspaceRuntimeResolutionError(
            f"workspace reference {workspace_ref} is not a workspace://<uuid> uri"
        ) from error
