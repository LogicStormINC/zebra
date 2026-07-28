from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from agent_core.domain import ArtifactAccessDescriptor
from agent_core.domain.artifact_payloads import StoredArtifactPayload
from agent_core.domain.identifiers import SessionId
from agent_core.ports import ArtifactPayloadStorePort, SessionArtifact
from agent_security import (
    ArtifactAccessProjection,
    PolicyProfile,
    build_artifact_access_audit_metadata,
    build_artifact_access_projection,
    serialize_artifact_access_projection,
)
from agent_security import (
    policy_rank as shared_policy_rank,
)
from agent_storage import (
    ControlPlaneStores,
    payload_for_artifact_uri,
)

from zebra_agent_api.responses import ApiResponse, conflict


@dataclass(frozen=True)
class ArtifactAccessContext:
    projection: ArtifactAccessProjection
    payload: StoredArtifactPayload | None

    @property
    def allowed(self) -> bool:
        return self.projection.allowed

    @property
    def access_class(self) -> str:
        return self.projection.access_class

    @property
    def required_policy_profile(self) -> str:
        return self.projection.required_policy_profile

    @property
    def session_policy_profile(self) -> str:
        return self.projection.session_policy_profile


def classify_session_artifact_access(
    *,
    stores: ControlPlaneStores,
    session_id: str,
    artifact: SessionArtifact,
) -> ArtifactAccessContext:
    payload = payload_record_for_uri(stores.artifact_payloads, artifact.uri)
    projection = build_artifact_access_projection(
        ArtifactAccessDescriptor(
            kind=artifact.kind,
            mime_type=payload.mime_type if payload is not None else None,
            uri=artifact.uri,
            preview_redacted=artifact.preview_state["redacted"],
            preview_truncated=artifact.preview_state["truncated"],
        ),
        session_policy_profile=session_policy_profile(stores, session_id),
    )
    return ArtifactAccessContext(
        projection=projection,
        payload=payload,
    )


def serialize_artifact_access(access: ArtifactAccessContext) -> dict[str, object]:
    return serialize_artifact_access_projection(access.projection)


def build_artifact_access_response(
    *,
    session_id: str,
    status: str,
    reason: str,
    access: ArtifactAccessContext,
) -> ApiResponse:
    response = conflict(
        session_id=session_id,
        status=status,
        reason=reason,
    )
    response.body["access"] = serialize_artifact_access(access)
    return response


def build_artifact_policy_denied_response(
    *,
    session_id: str,
    status: str,
    action: str,
    access: ArtifactAccessContext,
) -> ApiResponse:
    return build_artifact_access_response(
        session_id=session_id,
        status=status,
        reason=artifact_policy_denied_reason(access, action=action),
        access=access,
    )


def build_artifact_control_denied_response(
    *,
    session_id: str,
    status: str,
    action: str,
    access: ArtifactAccessContext,
) -> ApiResponse:
    return conflict(
        session_id=session_id,
        status=status,
        reason=artifact_policy_denied_reason(access, action=action),
    )


def build_artifact_unavailable_response(
    *,
    session_id: str,
    reason: str,
    access: ArtifactAccessContext,
) -> ApiResponse:
    return build_artifact_access_response(
        session_id=session_id,
        status="artifact_unavailable",
        reason=reason,
        access=access,
    )


def build_artifact_control_unavailable_response(
    *,
    session_id: str,
    status: str,
    reason: str,
) -> ApiResponse:
    return conflict(
        session_id=session_id,
        status=status,
        reason=reason,
    )


def build_artifact_control_success_response(
    *,
    session_id: str,
    artifact_id: str,
    status: str,
    access: ArtifactAccessContext,
    lifecycle: dict[str, object] | None,
) -> ApiResponse:
    return ApiResponse(
        status_code=200,
        body={
            "session_id": session_id,
            "artifact_id": artifact_id,
            "status": status,
            "access_class": access.access_class,
            "required_policy_profile": access.required_policy_profile,
            "lifecycle": lifecycle,
        },
    )


def build_artifact_access_metadata(
    access: ArtifactAccessContext,
    *,
    artifact: SessionArtifact,
    result_status: str,
    retrieval_status: str | None = None,
    reason: str | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    return build_artifact_access_audit_metadata(
        access.projection,
        artifact_id=artifact.artifact_id,
        result_status=result_status,
        retrieval_status=retrieval_status,
        reason=reason,
        extra=extra,
    )


def artifact_policy_denied_reason(
    access: ArtifactAccessContext,
    *,
    action: str,
) -> str:
    return f"artifact_{action}_requires_{access.required_policy_profile}_policy"


def payload_record_for_uri(
    payload_store: ArtifactPayloadStorePort,
    uri: str | None,
) -> StoredArtifactPayload | None:
    return payload_for_artifact_uri(payload_store, uri)


def session_policy_profile(stores: ControlPlaneStores, session_id: str) -> str:
    workspace = stores.workspaces.get_workspace(SessionId(UUID(session_id)))
    if workspace is None or workspace.policy_profile is None:
        return PolicyProfile.WORKSPACE_WRITE.value
    return workspace.policy_profile


def policy_rank(policy_profile: str) -> int:
    return shared_policy_rank(policy_profile)
