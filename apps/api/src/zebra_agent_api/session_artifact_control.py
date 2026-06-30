from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import (
    SessionArtifact,
    SQLiteArtifactPayloadStore,
    SQLiteArtifactStore,
    SQLiteProjectionStore,
    payload_for_artifact_uri,
    serialize_artifact_lifecycle,
)

from zebra_agent_api.artifact_access import (
    build_artifact_access_metadata,
    classify_session_artifact_access,
)
from zebra_agent_api.delivery_audit import record_delivery_audit
from zebra_agent_api.responses import ApiResponse, conflict


@dataclass(frozen=True)
class SessionArtifactControlApi:
    database_path: Path

    def prune_artifact(self, session_id: str, artifact_id: str) -> ApiResponse:
        artifact = self._resolve_session_artifact(session_id, artifact_id)
        if isinstance(artifact, ApiResponse):
            return artifact
        payload_store = SQLiteArtifactPayloadStore(self.database_path)
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
            self.database_path,
            session_id=session_id,
            artifact=artifact,
        )
        if not access.allowed:
            response = conflict(
                session_id=session_id,
                status="artifact_prune_denied",
                reason=(
                    f"artifact_prune_requires_{access.required_policy_profile}_policy"
                ),
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.prune",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_prune_denied",
                    extra={"payload_artifact_id": str(payload.artifact_id)},
                ),
            )
            return response
        already_pruned = payload.pruned_at is not None
        pruned = payload_store.prune_payload(payload.artifact_id)
        assert pruned is not None
        response = ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "artifact_id": artifact_id,
                "status": "already_pruned" if already_pruned else "pruned",
                "access_class": access.access_class,
                "required_policy_profile": access.required_policy_profile,
                "lifecycle": serialize_artifact_lifecycle(pruned),
            },
        )
        record_delivery_audit(
            database_path=self.database_path,
            session_id=session_id,
            action="session.artifact.prune",
            response=response,
            policy_profile=access.session_policy_profile,
            result_metadata=build_artifact_access_metadata(
                access,
                artifact=artifact,
                result_status=str(response.body["status"]),
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
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        for artifact in SQLiteArtifactStore(self.database_path).list_for_session(session_key):
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
        response = conflict(
            session_id=session_id,
            status="artifact_prune_unavailable",
            reason=reason,
        )
        record_delivery_audit(
            database_path=self.database_path,
            session_id=session_id,
            action="session.artifact.prune",
            response=response,
            result_metadata={
                "artifact_id": artifact_id,
                "result_status": "artifact_prune_unavailable",
                "unavailable_reason": reason,
            },
        )
        return response
