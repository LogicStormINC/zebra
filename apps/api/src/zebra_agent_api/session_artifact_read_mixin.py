from __future__ import annotations

import base64
from pathlib import Path

from agent_core.domain.artifact_objects import (
    ArtifactObjectIntegrityError,
    ArtifactObjectUnavailableError,
)
from agent_core.ports import (
    ArtifactPayloadReadPrunedError,
    ArtifactPayloadReadUnavailableError,
    SessionArtifact,
)
from agent_storage import (
    ControlPlaneStores,
    serialize_session_artifact_projection,
)

from zebra_agent_api.artifact_access import (
    ArtifactAccessContext,
    build_artifact_access_metadata,
    build_artifact_policy_denied_response,
    build_artifact_unavailable_response,
    classify_session_artifact_access,
    serialize_artifact_access,
)
from zebra_agent_api.artifact_payload_read import (
    inspect_artifact_payload,
    payload_reader,
    serialize_read_lifecycle,
    serialize_read_retrieval,
)
from zebra_agent_api.delivery_audit import record_delivery_audit
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_delivery_audit import SessionDeliveryAuditApi
from zebra_agent_api.session_identity_read import (
    _parse_session_id,
)


class SessionArtifactReadMixin:
    database_path: Path
    stores: ControlPlaneStores

    def get_session_artifacts(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        artifacts = self.stores.artifacts.list_for_session(session_key)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "artifacts": [self._serialize_artifact(artifact) for artifact in artifacts],
            },
        )

    def get_session_artifact_detail(self, session_id: str, artifact_id: str) -> ApiResponse:
        artifact = self._resolve_session_artifact(session_id, artifact_id)
        if isinstance(artifact, ApiResponse):
            return artifact
        access = classify_session_artifact_access(
            stores=self.stores,
            session_id=session_id,
            artifact=artifact,
        )
        if not access.allowed:
            response = build_artifact_policy_denied_response(
                session_id=session_id,
                status="artifact_access_denied",
                action="read",
                access=access,
            )
            record_delivery_audit(
                store=self.stores.delivery_audit,
                session_id=session_id,
                action="session.artifact.detail",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_access_denied",
                    retrieval_status="access_denied",
                ),
            )
            return response
        projection = self._serialize_artifact(artifact, access=access)
        response = ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "artifact": projection,
            },
        )
        retrieval = projection["retrieval"]
        assert isinstance(retrieval, dict)
        retrieval_status = retrieval["status"]
        assert isinstance(retrieval_status, str)
        record_delivery_audit(
            store=self.stores.delivery_audit,
            session_id=session_id,
            action="session.artifact.detail",
            response=response,
            policy_profile=access.session_policy_profile,
            result_metadata=build_artifact_access_metadata(
                access,
                artifact=artifact,
                result_status="ok",
                retrieval_status=retrieval_status,
                extra={
                    "source": artifact.source,
                    "kind": artifact.kind,
                    "preview_redacted": artifact.preview_state["redacted"],
                    "preview_truncated": artifact.preview_state["truncated"],
                },
            ),
        )
        return response

    def get_session_artifact_content(self, session_id: str, artifact_id: str) -> ApiResponse:
        artifact = self._resolve_session_artifact(session_id, artifact_id)
        if isinstance(artifact, ApiResponse):
            return artifact
        access = classify_session_artifact_access(
            stores=self.stores,
            session_id=session_id,
            artifact=artifact,
        )
        if not access.allowed:
            response = build_artifact_policy_denied_response(
                session_id=session_id,
                status="artifact_access_denied",
                action="read",
                access=access,
            )
            record_delivery_audit(
                store=self.stores.delivery_audit,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_access_denied",
                    retrieval_status="access_denied",
                ),
            )
            return response
        inspection = inspect_artifact_payload(self.stores, artifact)
        retrieval = serialize_read_retrieval(artifact.uri, inspection)
        status = str(retrieval["status"])
        unavailable_reason = _UNAVAILABLE_REASONS.get(status)
        if unavailable_reason is not None:
            return self._artifact_content_unavailable(
                session_id,
                artifact,
                access,
                reason=unavailable_reason,
                retrieval_status=status,
            )
        assert artifact.uri is not None
        assert inspection is not None
        try:
            payload = payload_reader(self.stores).read_payload_bytes(
                artifact.session_id,
                artifact.uri,
            )
        except ArtifactPayloadReadPrunedError:
            return self._artifact_content_unavailable(
                session_id,
                artifact,
                access,
                reason="artifact_payload_pruned",
                retrieval_status="payload_pruned",
            )
        except ArtifactPayloadReadUnavailableError:
            return self._artifact_content_unavailable(
                session_id,
                artifact,
                access,
                reason="artifact_payload_unavailable",
                retrieval_status="payload_unavailable",
            )
        except FileNotFoundError:
            return self._artifact_content_unavailable(
                session_id,
                artifact,
                access,
                reason="artifact_payload_missing",
                retrieval_status="payload_missing",
            )
        except (ArtifactObjectIntegrityError, ArtifactObjectUnavailableError):
            return self._artifact_content_unavailable(
                session_id,
                artifact,
                access,
                reason="artifact_payload_unavailable",
                retrieval_status="payload_unavailable",
            )
        response = ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "artifact_id": artifact.artifact_id,
                "status": "ok",
                "access": serialize_artifact_access(access),
                "encoding": "base64",
                "content_base64": base64.b64encode(payload).decode("ascii"),
                "size_bytes": len(payload),
            },
        )
        record_delivery_audit(
            store=self.stores.delivery_audit,
            session_id=session_id,
            action="session.artifact.content",
            response=response,
            policy_profile=access.session_policy_profile,
            result_metadata=build_artifact_access_metadata(
                access,
                artifact=artifact,
                result_status="ok",
                retrieval_status=status,
                extra={"size_bytes": len(payload)},
            ),
        )
        return response

    def _artifact_content_unavailable(
        self,
        session_id: str,
        artifact: SessionArtifact,
        access: ArtifactAccessContext,
        *,
        reason: str,
        retrieval_status: str,
    ) -> ApiResponse:
        response = build_artifact_unavailable_response(
            session_id=session_id,
            reason=reason,
            access=access,
        )
        record_delivery_audit(
            store=self.stores.delivery_audit,
            session_id=session_id,
            action="session.artifact.content",
            response=response,
            policy_profile=access.session_policy_profile,
            result_metadata=build_artifact_access_metadata(
                access,
                artifact=artifact,
                result_status="artifact_unavailable",
                retrieval_status=retrieval_status,
            ),
        )
        return response

    def get_session_delivery_audit(self, session_id: str) -> ApiResponse:
        return SessionDeliveryAuditApi(self.stores).get_delivery_audit(session_id)

    def _resolve_session_artifact(
        self,
        session_id: str,
        artifact_id: str,
    ) -> SessionArtifact | ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        artifacts = self.stores.artifacts.list_for_session(session_key)
        for artifact in artifacts:
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

    def _serialize_artifact(
        self,
        artifact: SessionArtifact,
        *,
        access: ArtifactAccessContext | None = None,
    ) -> dict[str, object]:
        resolved_access = access or classify_session_artifact_access(
            stores=self.stores,
            session_id=str(artifact.session_id),
            artifact=artifact,
        )
        inspection = inspect_artifact_payload(self.stores, artifact)
        lifecycle = serialize_read_lifecycle(inspection)
        projection = serialize_session_artifact_projection(
            artifact,
            lifecycle=lifecycle,
            retrieval=serialize_read_retrieval(artifact.uri, inspection),
        )
        if inspection is not None and inspection.file_name is not None:
            projection["delivery"] = {
                "file_name": inspection.file_name,
                "mime_type": inspection.mime_type,
                "size_bytes": inspection.size_bytes,
            }
        projection["access"] = serialize_artifact_access(resolved_access)
        return projection


_UNAVAILABLE_REASONS = {
    "indexed_only": "artifact_is_indexed_only",
    "external_reference": "artifact_uses_external_reference",
    "payload_missing": "artifact_payload_missing",
    "payload_pruned": "artifact_payload_pruned",
    "payload_unavailable": "artifact_payload_unavailable",
}
