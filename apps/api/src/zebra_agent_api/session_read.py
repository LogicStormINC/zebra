from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_runtime import WorkspaceDiffError, WorkspaceDiffService
from agent_storage import (
    SQLiteArtifactStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
)

from zebra_agent_api.approval_context import latest_approval_context
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_delivery_audit import SessionDeliveryAuditApi


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
        events = SQLiteEventStore(self.database_path).list_for_session(session_key)
        body: dict[str, object] = {
            "session_id": str(session.session_id),
            "title": session.title,
            "status": session.status.value,
            "current_sequence": session.current_sequence,
        }
        approval_context = latest_approval_context(events)
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
                        "metadata": artifact.metadata,
                    }
                    for artifact in artifacts
                ],
            },
        )

    def get_session_delivery_audit(self, session_id: str) -> ApiResponse:
        return SessionDeliveryAuditApi(self.database_path).get_delivery_audit(session_id)
