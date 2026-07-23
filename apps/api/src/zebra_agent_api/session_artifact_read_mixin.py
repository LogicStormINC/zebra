from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import urlparse

from agent_storage import (
    ControlPlaneStores,
    SessionArtifact,
    SQLiteArtifactPayloadStore,
    SQLiteArtifactStore,
    payload_for_artifact_uri,
    serialize_artifact_retrieval,
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
from zebra_agent_api.delivery_audit import record_delivery_audit
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_delivery_audit import SessionDeliveryAuditApi
from zebra_agent_api.session_identity_read import (
    _parse_session_id,
)
from zebra_agent_api.session_memory_overview_aggregation import (
    _artifact_lifecycle,
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
        artifacts = SQLiteArtifactStore(self.database_path).list_for_session(session_key)
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
            self.database_path,
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
                database_path=self.database_path,
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
            database_path=self.database_path,
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
            self.database_path,
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
                database_path=self.database_path,
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
        lifecycle = _artifact_lifecycle(self.database_path, artifact.uri)
        retrieval = serialize_artifact_retrieval(
            artifact.uri,
            lifecycle=lifecycle,
        )
        status = str(retrieval["status"])
        if status == "indexed_only":
            response = build_artifact_unavailable_response(
                session_id=session_id,
                reason="artifact_is_indexed_only",
                access=access,
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_unavailable",
                    retrieval_status=status,
                ),
            )
            return response
        if status == "external_reference":
            response = build_artifact_unavailable_response(
                session_id=session_id,
                reason="artifact_uses_external_reference",
                access=access,
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_unavailable",
                    retrieval_status=status,
                ),
            )
            return response
        if status == "payload_missing":
            response = build_artifact_unavailable_response(
                session_id=session_id,
                reason="artifact_payload_missing",
                access=access,
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_unavailable",
                    retrieval_status=status,
                ),
            )
            return response
        if status == "payload_pruned":
            response = build_artifact_unavailable_response(
                session_id=session_id,
                reason="artifact_payload_pruned",
                access=access,
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_unavailable",
                    retrieval_status=status,
                ),
            )
            return response
        assert artifact.uri is not None
        # CTX-ART-02: resolve artifact:// URI through the payload store to
        # obtain the volatile file:// access path for reading bytes.
        payload_store = SQLiteArtifactPayloadStore(self.database_path)
        stored_payload = payload_for_artifact_uri(payload_store, artifact.uri)
        read_uri = (
            stored_payload.access_uri or stored_payload.uri
            if stored_payload is not None
            else artifact.uri
        )
        read_path = Path(urlparse(read_uri).path)
        if not read_path.is_file():
            response = build_artifact_unavailable_response(
                session_id=session_id,
                reason="artifact_payload_missing",
                access=access,
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_unavailable",
                    retrieval_status="payload_missing",
                ),
            )
            return response
        payload = read_path.read_bytes()
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
            database_path=self.database_path,
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

    def get_session_delivery_audit(self, session_id: str) -> ApiResponse:
        return SessionDeliveryAuditApi(self.database_path, self.stores).get_delivery_audit(
            session_id
        )

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
        artifacts = SQLiteArtifactStore(self.database_path).list_for_session(session_key)
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
            self.database_path,
            stores=self.stores,
            session_id=str(artifact.session_id),
            artifact=artifact,
        )
        lifecycle = _artifact_lifecycle(self.database_path, artifact.uri)
        projection = serialize_session_artifact_projection(
            artifact,
            lifecycle=lifecycle,
        )
        projection["access"] = serialize_artifact_access(resolved_access)
        return projection
