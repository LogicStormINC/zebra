from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_core.application import (
    ApprovalDecisionAction,
    ApprovalDecisionCommand,
    ApprovalDecisionService,
)
from agent_core.application.session_projection import apply_event
from agent_core.domain.identifiers import SessionId
from agent_storage import ControlPlaneStores

from zebra_agent_api.approval_context import serialize_approval_context
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_payloads import parse_approval_decision_payload


class ApiApprovalControlMixin:
    database_path: Path
    stores: ControlPlaneStores
    _parse_session_id: Callable[[str], SessionId | ApiResponse]

    def approve(self, approval_id: str, payload: dict[str, object]) -> ApiResponse:
        return self._record_approval_decision(
            approval_id,
            payload,
            action=ApprovalDecisionAction.GRANT,
            decision="approve",
        )

    def reject(self, approval_id: str, payload: dict[str, object]) -> ApiResponse:
        return self._record_approval_decision(
            approval_id,
            payload,
            action=ApprovalDecisionAction.REJECT,
            decision="reject",
        )

    def _record_approval_decision(
        self,
        approval_id: str,
        payload: dict[str, object],
        *,
        action: ApprovalDecisionAction,
        decision: str,
    ) -> ApiResponse:
        parsed = parse_approval_decision_payload(
            payload,
            default_reason=f"{decision} via API",
        )
        if isinstance(parsed, ApiResponse):
            return parsed

        session_key = self._parse_session_id(approval_id)
        if isinstance(session_key, ApiResponse):
            return session_key

        projection_store = self.stores.sessions
        session = projection_store.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"approval_id": approval_id, "status": "not_found"},
            )
        try:
            event = ApprovalDecisionService().build_event(
                session=session,
                next_sequence=session.current_sequence + 1,
                command=ApprovalDecisionCommand(
                    action=action,
                    operator=parsed["operator"],
                    reason=parsed["reason"],
                ),
            )
        except ValueError as error:
            return conflict(
                session_id=approval_id,
                status="invalid_state",
                reason=str(error),
            )
        event_store = self.stores.events
        approval_context = serialize_approval_context(session.approval_context)
        event_store.append(event)
        updated_session = projection_store.save_session(apply_event(session, event))
        task_id = self.stores.tasks.ensure_for_session(session_key).task_id
        body: dict[str, object] = {
            "approval_id": approval_id,
            "session_id": str(task_id),
            "decision": decision,
            "event_type": event.event_type.value,
            "sequence": event.sequence,
            "status": updated_session.status.value,
        }
        if approval_context is not None:
            body["approval_context"] = approval_context
        return ApiResponse(status_code=200, body=body)
