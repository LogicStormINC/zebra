from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.memories import MemoryQuery, MemoryStatus
from agent_runtime import WorkspaceDiffError, WorkspaceDiffService
from agent_storage import (
    SessionArtifact,
    SQLiteArtifactPayloadStore,
    SQLiteArtifactStore,
    SQLiteEventStore,
    SQLiteMemoryStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
    payload_for_artifact_uri,
    serialize_artifact_lifecycle,
    serialize_artifact_retrieval,
    serialize_session_artifact_projection,
)

from zebra_agent_api.approval_context import serialize_approval_context
from zebra_agent_api.artifact_access import (
    ArtifactAccessContext,
    build_artifact_access_metadata,
    build_artifact_policy_denied_response,
    build_artifact_unavailable_response,
    classify_session_artifact_access,
    serialize_artifact_access,
)
from zebra_agent_api.delivery_audit import record_delivery_audit
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_delivery_audit import SessionDeliveryAuditApi
from zebra_agent_api.workspace_read import serialize_workspace_projection


@dataclass(frozen=True)
class SessionReadApi:
    database_path: Path

    def get_session(self, session_id: str) -> ApiResponse:
        session_key = SessionId(UUID(session_id))
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={
                    "session_id": session_id,
                    "status": "not_found",
                },
            )
        body: dict[str, object] = {
            "session_id": str(session.session_id),
            "title": session.title,
            "status": session.status.value,
            "current_sequence": session.current_sequence,
        }
        workspace = SQLiteWorkspaceProjectionStore(self.database_path).get_workspace(session_key)
        serialized_workspace = serialize_workspace_projection(workspace)
        if serialized_workspace is not None:
            body["workspace"] = serialized_workspace
        approval_context = serialize_approval_context(session.approval_context)
        if approval_context is not None:
            body["approval_context"] = approval_context
        return ApiResponse(
            status_code=200,
            body=body,
        )

    def get_session_stream(self, session_id: str) -> ApiResponse:
        session_key = SessionId(UUID(session_id))
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={
                    "session_id": session_id,
                    "status": "not_found",
                },
            )
        events = SQLiteEventStore(self.database_path).list_for_session(session_key)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "events": [
                    {
                        "event_id": str(event.event_id),
                        "sequence": event.sequence,
                        "event_type": event.event_type.value,
                        "actor": event.actor.value,
                        "created_at": event.created_at.isoformat(),
                        "payload": event.payload,
                    }
                    for event in events
                ],
            },
        )

    def get_session_diff(self, session_id: str) -> ApiResponse:
        session_key = SessionId(UUID(session_id))
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        workspace_root = session_workspace_root(
            SQLiteEventStore(self.database_path).list_for_session(session_key)
        )
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="diff_unavailable",
                reason="session workspace_root is unavailable",
            )
        try:
            diff = WorkspaceDiffService().read_diff(workspace_root)
        except WorkspaceDiffError as error:
            return conflict(
                session_id=session_id,
                status="diff_unavailable",
                reason=str(error),
            )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "workspace": str(diff.workspace_root),
                "clean": diff.clean,
                "git_status": diff.git_status,
                "diff": diff.diff,
            },
        )

    def get_session_memory(self, session_id: str) -> ApiResponse:
        session_key = SessionId(UUID(session_id))
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        workspace_root = session_workspace_root(
            SQLiteEventStore(self.database_path).list_for_session(session_key)
        )
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        records = SQLiteMemoryStore(self.database_path).list(
            MemoryQuery(
                repo_id=str(workspace_root),
                statuses=(
                    MemoryStatus.CANDIDATE,
                    MemoryStatus.CONFIRMED,
                    MemoryStatus.SUPERSEDED,
                    MemoryStatus.EXPIRED,
                ),
            )
        )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "memories": [record.model_dump(mode="json") for record in records],
            },
        )

    def get_session_artifacts(self, session_id: str) -> ApiResponse:
        session_key = SessionId(UUID(session_id))
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
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
                "artifacts": [
                    self._serialize_artifact(artifact)
                    for artifact in artifacts
                ],
            },
        )

    def get_session_artifact_detail(self, session_id: str, artifact_id: str) -> ApiResponse:
        artifact = self._resolve_session_artifact(session_id, artifact_id)
        if isinstance(artifact, ApiResponse):
            return artifact
        access = classify_session_artifact_access(
            self.database_path,
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
        payload = Path(urlparse(artifact.uri).path).read_bytes()
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
        return SessionDeliveryAuditApi(self.database_path).get_delivery_audit(session_id)

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


def _artifact_lifecycle(database_path: Path, uri: str | None) -> dict[str, object] | None:
    payload = payload_for_artifact_uri(SQLiteArtifactPayloadStore(database_path), uri)
    return serialize_artifact_lifecycle(payload)
