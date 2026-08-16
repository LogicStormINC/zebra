"""Workspace Control Plane command and read surface (cloud profile)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID, uuid4

from agent_core.domain.workspace_control import (
    WorkspaceId,
    WorkspaceInstance,
    WorkspaceSource,
)

from zebra_agent_api.responses import ApiResponse, bad_request

WORKSPACE_URI_PREFIX = "workspace://"


class WorkspaceControlStorePort(Protocol):
    """The API only submits commands and reads projections."""

    def create_pending(
        self,
        source: WorkspaceSource,
        *,
        workspace_id: WorkspaceId,
        quota_bytes: int,
        owner_session_id: UUID | None,
        idempotency_key: str,
    ) -> tuple[WorkspaceInstance, object]: ...

    def get(self, workspace_id: WorkspaceId) -> WorkspaceInstance | None: ...


class WorkspaceApiMixin:
    workspace_control_store: WorkspaceControlStorePort | None = None

    def create_workspace(self, payload: dict[str, object]) -> ApiResponse:
        store = self.workspace_control_store
        if store is None:
            return bad_request("workspace control plane requires the cloud profile")
        source_value = payload.get("source")
        if not isinstance(source_value, dict):
            return bad_request("source must be an object describing the workspace source")
        quota_value = payload.get("quota_bytes")
        if not isinstance(quota_value, int) or isinstance(quota_value, bool) or quota_value <= 0:
            return bad_request("quota_bytes must be a positive integer")
        try:
            source = WorkspaceSource.model_validate(source_value)
        except ValueError as error:
            return bad_request(f"workspace source is invalid: {error}")
        idempotency_key = payload.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            return bad_request("idempotency_key must be a non-blank string")
        workspace_id = WorkspaceId(uuid4())
        instance, _receipt = store.create_pending(
            source,
            workspace_id=workspace_id,
            quota_bytes=quota_value,
            owner_session_id=None,
            idempotency_key=idempotency_key.strip(),
        )
        return ApiResponse(
            status_code=201,
            body={
                "workspace_id": str(instance.workspace_id),
                "workspace_uri": f"{WORKSPACE_URI_PREFIX}{instance.workspace_id}",
                "state": instance.state.value,
            },
        )

    def get_workspace(self, workspace_id: str) -> ApiResponse:
        store = self.workspace_control_store
        if store is None:
            return bad_request("workspace control plane requires the cloud profile")
        try:
            key = WorkspaceId(UUID(workspace_id))
        except ValueError:
            return bad_request("workspace_id must be a UUID")
        instance = store.get(key)
        if instance is None:
            return ApiResponse(
                status_code=404,
                body={"workspace_id": workspace_id, "status": "not_found"},
            )
        return ApiResponse(status_code=200, body=_projection(instance))


def _projection(instance: WorkspaceInstance) -> dict[str, object]:
    return {
        "workspace_id": str(instance.workspace_id),
        "state": instance.state.value,
        "source_kind": instance.source.kind.value,
        "materialized_revision": instance.materialized_revision,
        "content_digest": instance.content_digest,
        "quota_bytes": instance.quota_bytes,
    }
