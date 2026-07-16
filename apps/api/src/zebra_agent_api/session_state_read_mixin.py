from __future__ import annotations

from pathlib import Path

from agent_core.application import attachment_refs_from_event
from agent_runtime import WorkspaceDiffError, WorkspaceDiffService
from agent_storage import SQLiteEventStore, SQLiteProjectionStore, SQLiteWorkspaceProjectionStore

from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_inventory,
    read_repo_memory_queue,
    read_repo_memory_queue_summary,
)
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_identity_read import (
    _parse_session_id,
)
from zebra_agent_api.session_summary import serialize_session_summary


class SessionStateReadMixin:
    database_path: Path

    def get_session(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={
                    "session_id": session_id,
                    "status": "not_found",
                },
            )
        workspace = SQLiteWorkspaceProjectionStore(self.database_path).get_workspace(session_key)
        body = serialize_session_summary(session, workspace)
        events = SQLiteEventStore(self.database_path).list_for_session(session_key)
        attachments = [
            ref.to_mapping() for event in events for ref in attachment_refs_from_event(event)
        ]
        if attachments:
            body["attachments"] = attachments
        return ApiResponse(
            status_code=200,
            body=body,
        )

    def get_session_stream(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
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
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
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
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "memories": read_repo_memory_inventory(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                ),
            },
        )

    def get_session_memory_queue(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "memories": read_repo_memory_queue(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                ),
            },
        )

    def get_session_memory_queue_summary(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                **read_repo_memory_queue_summary(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                ),
            },
        )
