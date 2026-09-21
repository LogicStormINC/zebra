from __future__ import annotations

from pathlib import Path

from agent_core.application import (
    GovernedMemoryScope,
    attachment_refs_from_event,
    governed_memory_scope_from_events,
    serialize_scoped_memory_inventory,
)
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.memories import MemoryStatus
from agent_runtime import WorkspaceDiffError, WorkspaceDiffService
from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_identity_read import (
    _parse_session_id,
)
from zebra_agent_api.session_summary import serialize_session_summary


class SessionStateReadMixin:
    database_path: Path
    stores: ControlPlaneStores

    def get_session(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={
                    "session_id": session_id,
                    "status": "not_found",
                },
            )
        workspace = self.stores.workspaces.get_workspace(session_key)
        body = serialize_session_summary(session, workspace)
        events = self.stores.events.list_for_session(session_key)
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
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={
                    "session_id": session_id,
                    "status": "not_found",
                },
            )
        events = self.stores.events.list_for_session(session_key)
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
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        workspace_root = session_workspace_root(self.stores.events.list_for_session(session_key))
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
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(self.stores.events.list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        scope = governed_memory_scope_from_events(
            events,
            fallback_repo_id=str(workspace_root),
        )
        if scope is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session Memory principal scope is ambiguous",
            )
        records = self.stores.memories.list(
            scope.query(limit=500).model_copy(
                update={
                    "statuses": (
                        MemoryStatus.CANDIDATE,
                        MemoryStatus.CONFIRMED,
                        MemoryStatus.SUPERSEDED,
                        MemoryStatus.EXPIRED,
                    )
                }
            )
        )
        body: dict[str, object] = {
            "session_id": session_id,
            "repo_id": scope.repo_id,
            "memories": serialize_scoped_memory_inventory(
                records,
                self.stores.events.list_for_session,
            ),
        }
        if _is_cloud_memory_scope(scope):
            body.update(
                {
                    "scope": _memory_scope_payload(scope),
                    "runtime": _memory_runtime_payload(self.stores, session_id, events),
                }
            )
        return ApiResponse(status_code=200, body=body)

    def get_session_memory_queue(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(self.stores.events.list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        scope = governed_memory_scope_from_events(
            events,
            fallback_repo_id=str(workspace_root),
        )
        if scope is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session Memory principal scope is ambiguous",
            )
        records = self.stores.memories.list(
            scope.query(limit=500).model_copy(update={"statuses": (MemoryStatus.CANDIDATE,)})
        )
        body: dict[str, object] = {
            "session_id": session_id,
            "repo_id": scope.repo_id,
            "memories": serialize_scoped_memory_inventory(
                records,
                self.stores.events.list_for_session,
            ),
        }
        if _is_cloud_memory_scope(scope):
            body["scope"] = _memory_scope_payload(scope)
        return ApiResponse(status_code=200, body=body)

    def get_session_memory_queue_summary(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(self.stores.events.list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        scope = governed_memory_scope_from_events(
            events,
            fallback_repo_id=str(workspace_root),
        )
        if scope is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session Memory principal scope is ambiguous",
            )
        pending = self.stores.memories.list(
            scope.query(limit=500).model_copy(update={"statuses": (MemoryStatus.CANDIDATE,)})
        )
        latest = max(pending, key=lambda item: item.updated_at) if pending else None
        body: dict[str, object] = {
            "session_id": session_id,
            "repo_id": scope.repo_id,
            "pending_count": len(pending),
            "queue_status": "pending" if pending else "empty",
            "latest_memory_id": None if latest is None else str(latest.memory_id),
            "latest_updated_at": None if latest is None else latest.updated_at.isoformat(),
        }
        if _is_cloud_memory_scope(scope):
            body["scope"] = _memory_scope_payload(scope)
        return ApiResponse(status_code=200, body=body)


def _memory_scope_payload(scope: GovernedMemoryScope) -> dict[str, object]:
    return {
        "repo_id": scope.repo_id,
        "user_id": scope.user_id,
        "tenant_id": scope.tenant_id,
        "authority_issuer": scope.authority_issuer,
        "namespace_id": scope.namespace_id,
        "definition_id": (None if scope.definition_id is None else str(scope.definition_id)),
    }


def _is_cloud_memory_scope(scope: GovernedMemoryScope) -> bool:
    return scope.user_id is not None or scope.authority_issuer is not None


def _memory_runtime_payload(
    stores: ControlPlaneStores,
    session_id: str,
    events: list[SessionEvent],
) -> dict[str, object]:
    closes = [
        event
        for event in events
        if event.event_type in {EventType.TURN_COMPLETED, EventType.SESSION_COMPLETED}
    ]
    finalization = None
    if closes:
        receipt = stores.idempotency.get(
            action="worker-memory-finalization-recovery",
            idempotency_key=f"{session_id}:{closes[-1].sequence}",
        )
        finalization = None if receipt is None else receipt.response_body
    selected = next(
        (
            event.payload
            for event in reversed(events)
            if event.event_type is EventType.MEMORY_CONTEXT_SELECTED
        ),
        None,
    )
    checkpoint = next(
        (
            event.payload
            for event in reversed(events)
            if event.event_type is EventType.MEMORY_EXTRACTION_COMPLETED
        ),
        None,
    )
    return {
        "finalization": finalization,
        "extraction": checkpoint,
        "last_recall": selected,
    }
