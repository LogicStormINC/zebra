from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.application.approvals import (
    ApprovalDecisionAction,
    ApprovalDecisionCommand,
    ApprovalDecisionService,
)
from agent_core.application.session_projection import apply_event
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import ApprovalContext
from agent_storage import SQLiteEventStore, SQLiteProjectionStore


def record_approval_decision(
    *,
    database_path: Path,
    approval_id: str,
    decision: str,
    operator: str,
    reason: str,
) -> dict[str, object]:
    session_id = SessionId(UUID(approval_id))
    projection_store = SQLiteProjectionStore(database_path)
    session = projection_store.get_session(session_id)
    if session is None:
        return {
            "approval_id": approval_id,
            "database": str(database_path),
            "status": "not_found",
        }
    action = (
        ApprovalDecisionAction.GRANT
        if decision == "approve"
        else ApprovalDecisionAction.REJECT
    )
    try:
        event = ApprovalDecisionService().build_event(
            session=session,
            next_sequence=session.current_sequence + 1,
            command=ApprovalDecisionCommand(
                action=action,
                operator=operator,
                reason=reason or f"{decision} via CLI",
            ),
        )
    except ValueError as exc:
        return {
            "session_id": approval_id,
            "database": str(database_path),
            "status": "invalid_state",
            "reason": str(exc),
        }
    SQLiteEventStore(database_path).append(event)
    updated_session = projection_store.save_session(apply_event(session, event))
    payload: dict[str, object] = {
        "approval_id": approval_id,
        "session_id": approval_id,
        "database": str(database_path),
        "decision": decision,
        "event_type": event.event_type.value,
        "sequence": event.sequence,
        "status": updated_session.status.value,
    }
    approval_context = _serialize_approval_context(session.approval_context)
    if approval_context is not None:
        payload["approval_context"] = approval_context
    return payload


def _serialize_approval_context(context: ApprovalContext | None) -> dict[str, object] | None:
    if context is None:
        return None
    payload: dict[str, object] = {
        "tool_name": context.tool_name,
        "reason": context.reason,
        "policy_profile": context.policy_profile,
    }
    for field in ("route", "target", "network_profile"):
        value = getattr(context, field)
        if isinstance(value, str) and value.strip():
            payload[field] = value
    if context.scope:
        payload["scope"] = list(context.scope)
    return payload
