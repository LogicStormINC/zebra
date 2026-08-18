from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_storage import ControlPlaneStores

from zebra_agent_api.approval_context import serialize_approval_context
from zebra_agent_api.responses import ApiResponse


@dataclass(frozen=True)
class ApprovalReadApi:
    stores: ControlPlaneStores

    def list_approvals(self) -> ApiResponse:
        task_store = self.stores.tasks
        return ApiResponse(
            status_code=200,
            body={
                "approvals": [
                    _approval_summary(
                        session,
                        task_id=str(task_store.ensure_for_session(session.session_id).task_id),
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
        task_id = str(self.stores.tasks.ensure_for_session(session.session_id).task_id)
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
