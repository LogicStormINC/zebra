from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import ControlPlaneStores

from zebra_agent_api.approval_context import serialize_approval_context
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.task_responses import MAX_TASK_LIMIT


@dataclass(frozen=True)
class ApprovalReadApi:
    stores: ControlPlaneStores

    def list_approvals(
        self,
        *,
        authorize_task: Callable[[TaskId], ApiResponse | None] | None = None,
    ) -> ApiResponse:
        if authorize_task is not None:
            items = []
            for task in self.stores.tasks.list_tasks(limit=MAX_TASK_LIMIT):
                denied = authorize_task(task.task_id)
                if denied is not None:
                    if denied.status_code == 404:
                        continue
                    return denied
                session = self.stores.sessions.get_session(task.active_segment_id)
                if session is not None and session.status is SessionStatus.WAITING_APPROVAL:
                    mapped = self.stores.tasks.task_id_for_session(session.session_id)
                    if mapped != task.task_id:
                        return ApiResponse(
                            409, {"status": "projection_not_ready", "retryable": True}
                        )
                    items.append(_approval_summary(session, task_id=str(task.task_id)))
            return ApiResponse(200, {"approvals": items})
        task_store = self.stores.tasks
        return ApiResponse(
            status_code=200,
            body={
                "approvals": [
                    _approval_summary(
                        session,
                        task_id=str(
                            task_store.task_id_for_session(session.session_id) or session.session_id
                        ),
                    )
                    for session in self.stores.sessions.list_waiting_approval_sessions()
                ]
            },
        )

    def get_approval(self, approval_id: str) -> ApiResponse:
        session = self.stores.sessions.get_session(SessionId(UUID(approval_id)))
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"approval_id": approval_id, "status": "not_found"},
            )
        # Local legacy projections can be observed without adopting a Task.
        task_id = str(
            self.stores.tasks.task_id_for_session(session.session_id) or session.session_id
        )
        return ApiResponse(status_code=200, body=_approval_summary(session, task_id=task_id))


def _approval_summary(session: Session, *, task_id: str) -> dict[str, object]:
    body: dict[str, object] = {
        "approval_id": str(session.session_id),
        "session_id": task_id,
        "title": session.title,
        "status": session.status.value,
        "current_sequence": session.current_sequence,
    }
    approval_context = serialize_approval_context(session.approval_context)
    if approval_context is not None:
        body["approval_context"] = approval_context
    return body
