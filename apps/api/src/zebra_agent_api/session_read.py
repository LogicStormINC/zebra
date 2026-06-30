from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_runtime import WorkspaceDiffError, WorkspaceDiffService
from agent_storage import (
    SessionArtifact,
    SQLiteArtifactStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)

from zebra_agent_api.approval_context import serialize_approval_context
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
                    {
                        "artifact_id": artifact.artifact_id,
                        "sequence": artifact.sequence,
                        "source": artifact.source,
                        "kind": artifact.kind,
                        "label": artifact.label,
                        "uri": artifact.uri,
                        "preview": artifact.preview,
                        "preview_state": artifact.preview_state,
                        "metadata": artifact.metadata,
                    }
                    for artifact in artifacts
                ],
            },
        )

    def get_session_artifact_detail(self, session_id: str, artifact_id: str) -> ApiResponse:
        artifact = self._resolve_session_artifact(session_id, artifact_id)
        if isinstance(artifact, ApiResponse):
            return artifact
        response = ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "artifact": {
                    "artifact_id": artifact.artifact_id,
                    "sequence": artifact.sequence,
                    "source": artifact.source,
                    "kind": artifact.kind,
                    "label": artifact.label,
                    "uri": artifact.uri,
                    "preview": artifact.preview,
                    "preview_state": artifact.preview_state,
                    "metadata": artifact.metadata,
                    "retrieval": _artifact_retrieval(artifact.uri),
                },
            },
        )
        body_artifact = response.body["artifact"]
        assert isinstance(body_artifact, dict)
        retrieval = body_artifact["retrieval"]
        assert isinstance(retrieval, dict)
        retrieval_status = retrieval["status"]
        assert isinstance(retrieval_status, str)
        record_delivery_audit(
            database_path=self.database_path,
            session_id=session_id,
            action="session.artifact.detail",
            response=response,
            result_metadata={
                "artifact_id": artifact.artifact_id,
                "source": artifact.source,
                "kind": artifact.kind,
                "preview_redacted": artifact.preview_state["redacted"],
                "preview_truncated": artifact.preview_state["truncated"],
                "retrieval_status": retrieval_status,
            },
        )
        return response

    def get_session_artifact_content(self, session_id: str, artifact_id: str) -> ApiResponse:
        artifact = self._resolve_session_artifact(session_id, artifact_id)
        if isinstance(artifact, ApiResponse):
            return artifact
        retrieval = _artifact_retrieval(artifact.uri)
        status = retrieval["status"]
        if status == "indexed_only":
            response = conflict(
                session_id=session_id,
                status="artifact_unavailable",
                reason="artifact_is_indexed_only",
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                result_metadata={"artifact_id": artifact.artifact_id, "retrieval_status": status},
            )
            return response
        if status == "external_reference":
            response = conflict(
                session_id=session_id,
                status="artifact_unavailable",
                reason="artifact_uses_external_reference",
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                result_metadata={"artifact_id": artifact.artifact_id, "retrieval_status": status},
            )
            return response
        if status == "payload_missing":
            response = conflict(
                session_id=session_id,
                status="artifact_unavailable",
                reason="artifact_payload_missing",
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                result_metadata={"artifact_id": artifact.artifact_id, "retrieval_status": status},
            )
            return response
        assert artifact.uri is not None
        payload = Path(urlparse(artifact.uri).path).read_bytes()
        response = ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "artifact_id": artifact.artifact_id,
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
            result_metadata={
                "artifact_id": artifact.artifact_id,
                "retrieval_status": status,
                "size_bytes": len(payload),
            },
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


def _artifact_retrieval(uri: str | None) -> dict[str, object]:
    if uri is None:
        return {
            "status": "indexed_only",
            "retrievable": False,
            "uri": None,
        }
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return {
            "status": "external_reference",
            "retrievable": False,
            "uri": uri,
        }
    payload_path = Path(parsed.path)
    return {
        "status": "payload_available" if payload_path.is_file() else "payload_missing",
        "retrievable": payload_path.is_file(),
        "uri": uri,
    }
