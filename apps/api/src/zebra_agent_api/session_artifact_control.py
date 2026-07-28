from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.ports import SessionArtifact
from agent_security import build_artifact_control_audit_metadata
from agent_storage import (
    ControlPlaneStores,
    payload_for_artifact_uri,
    serialize_artifact_lifecycle,
)

from zebra_agent_api.artifact_access import (
    build_artifact_control_denied_response,
    build_artifact_control_success_response,
    build_artifact_control_unavailable_response,
    classify_session_artifact_access,
)
from zebra_agent_api.delivery_audit import record_delivery_audit
from zebra_agent_api.responses import ApiResponse


@dataclass(frozen=True)
class SessionArtifactControlApi:
    database_path: Path
    stores: ControlPlaneStores

    def prune_artifact(self, session_id: str, artifact_id: str) -> ApiResponse:
        artifact = self._resolve_session_artifact(session_id, artifact_id)
        if isinstance(artifact, ApiResponse):
            return artifact
        payload_store = self.stores.artifact_payloads
        payload = payload_for_artifact_uri(payload_store, artifact.uri)
        if artifact.uri is None:
            return self._unavailable(
                session_id,
                artifact_id,
                reason="artifact_is_indexed_only",
            )
        if payload is None:
            return self._unavailable(
                session_id,
                artifact_id,
                reason="artifact_uses_external_reference",
            )
        access = classify_session_artifact_access(
            stores=self.stores,
            session_id=session_id,
            artifact=artifact,
        )
        if not access.allowed:
            response = build_artifact_control_denied_response(
                session_id=session_id,
                status="artifact_prune_denied",
                action="prune",
                access=access,
            )
            record_delivery_audit(
                store=self.stores.delivery_audit,
                session_id=session_id,
                action="session.artifact.prune",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_control_audit_metadata(
                    artifact_id=artifact.artifact_id,
                    result_status="artifact_prune_denied",
                    projection=access.projection,
                    extra={"payload_artifact_id": str(payload.artifact_id)},
                ),
            )
            return response
        already_pruned = payload.pruned_at is not None
        pruned = payload_store.prune_payload(payload.artifact_id)
        assert pruned is not None
        response = build_artifact_control_success_response(
            session_id=session_id,
            artifact_id=artifact_id,
            status="already_pruned" if already_pruned else "pruned",
            access=access,
            lifecycle=serialize_artifact_lifecycle(pruned),
        )
        record_delivery_audit(
            store=self.stores.delivery_audit,
            session_id=session_id,
            action="session.artifact.prune",
            response=response,
            policy_profile=access.session_policy_profile,
            result_metadata=build_artifact_control_audit_metadata(
                artifact_id=artifact.artifact_id,
                result_status=str(response.body["status"]),
                projection=access.projection,
                extra={
                    "payload_artifact_id": str(pruned.artifact_id),
                    "lifecycle_status": pruned.lifecycle_status.value,
                },
            ),
        )
        return response

    def _resolve_session_artifact(
        self,
        session_id: str,
        artifact_id: str,
    ) -> SessionArtifact | ApiResponse:
        session_key = SessionId(UUID(session_id))
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        for artifact in self.stores.artifacts.list_for_session(session_key):
            if artifact.artifact_id == artifact_id:
                return artifact
        return ApiResponse(
            status_code=404,
            body={
                "session_id": session_id,
                "artifact_id": artifact_id,
                "status": "not_found",
            },
        )

    def _unavailable(
        self,
        session_id: str,
        artifact_id: str,
        *,
        reason: str,
    ) -> ApiResponse:
        response = build_artifact_control_unavailable_response(
            session_id=session_id,
            status="artifact_prune_unavailable",
            reason=reason,
        )
        record_delivery_audit(
            store=self.stores.delivery_audit,
            session_id=session_id,
            action="session.artifact.prune",
            response=response,
            result_metadata=build_artifact_control_audit_metadata(
                artifact_id=artifact_id,
                result_status="artifact_prune_unavailable",
                unavailable_reason=reason,
            ),
        )
        return response
