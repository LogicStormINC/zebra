"""Resolve workspace:// references into materialized runtime roots.

The Worker's runtime seam (CLOUD-WORKSPACE-CP-RT-01): plain paths pass
through unchanged for the local profile; control-plane bound references
resolve through the provisioner with fail-closed semantics and revision
fencing for continuations.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.workspace_control import WorkspaceId, WorkspaceLifecycleState

from agent_runtime.workspace_provisioner import PostgresWorkspaceProvisioner

WORKSPACE_URI_PREFIX = "workspace://"


class WorkspaceRuntimeResolutionError(ValueError):
    """Raised when a bound workspace cannot be resolved fail-closed."""


class WorkspaceRuntimeResolver:
    def __init__(self, provisioner: PostgresWorkspaceProvisioner) -> None:
        self._provisioner = provisioner

    def resolve(self, workspace_ref: str, *, session_id: UUID) -> Path:
        if not _is_workspace_reference(workspace_ref):
            return Path(workspace_ref)
        workspace_id = _workspace_id(workspace_ref)
        if self._provisioner.store.get(workspace_id) is None:
            raise WorkspaceRuntimeResolutionError(
                f"workspace {workspace_ref} is unknown to the control plane"
            )
        instance = self._provisioner.provision_existing(workspace_id)
        return self._require_materialized(workspace_ref, instance)

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
        return self._require_materialized(workspace_ref, instance)

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
