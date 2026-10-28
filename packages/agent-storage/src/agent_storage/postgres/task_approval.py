"""Exact, atomic Cloud approval decisions using existing events and command outbox."""

import json
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from agent_core.application.approvals import (
    ApprovalDecisionAction,
    ApprovalDecisionCommand,
    ApprovalDecisionService,
)
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import apply_event as apply_workspace
from agent_core.contracts.session_commands import (
    SessionCommand,
    SessionCommandKind,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import TaskId

from agent_storage.postgres.events import append_event_in_transaction, read_event_in_transaction
from agent_storage.postgres.projections import (
    get_session_in_transaction,
    save_session_in_transaction,
)
from agent_storage.postgres.task_replay_headers import read_latest_run_header
from agent_storage.postgres.workspaces import (
    get_workspace_in_transaction,
    save_workspace_in_transaction,
)


def task_approval(
    database: Any,
    task_id: TaskId,
    run_id: str,
    decision: dict[str, Any] | None = None,
    receipt_event_id: str | None = None,
) -> dict[str, Any]:
    ns = database.deployment_namespace
    with database.connect_task_io() as c:
        # Stream first, then Task: same ordering as native Event append/Task triggers.
        task = c.execute(
            "SELECT active_segment_id FROM agent_tasks WHERE deployment_namespace=%s "
            "AND task_id=%s",
            (ns, task_id),
        ).fetchone()
        if task is None:
            raise ValueError("approval_task_unavailable")
        sid = task["active_segment_id"]
        head = c.execute(
            "SELECT current_version FROM session_streams WHERE deployment_namespace=%s "
            "AND session_id=%s FOR UPDATE",
            (ns, sid),
        ).fetchone()
        current = c.execute(
            "SELECT active_segment_id FROM agent_tasks WHERE deployment_namespace=%s "
            "AND task_id=%s FOR SHARE",
            (ns, task_id),
        ).fetchone()
        if current is None or current["active_segment_id"] != sid or head is None:
            raise ValueError("approval_task_changed")
        run = read_latest_run_header(c, ns, task_id)
        if run.run_id != run_id or run.anchor is None or run.stop is not None:
            raise ValueError("approval_run_changed")
        if receipt_event_id is not None:
            key = f"approval-decision:{sid}:{receipt_event_id}"
            prior = c.execute(
                "SELECT event_id FROM session_events WHERE deployment_namespace=%s "
                "AND session_id=%s AND idempotency_key=%s",
                (ns, sid, key),
            ).fetchone()
            if prior:
                saved = _bounded_event(c, ns, prior["event_id"])
                if saved.payload.get("run_id") != run_id:
                    raise ValueError("approval_run_changed")
                return {
                    "approval_event_id": receipt_event_id,
                    "run_id": run_id,
                    "decision": "approve"
                    if saved.event_type is EventType.APPROVAL_GRANTED
                    else "reject",
                    "replayed": True,
                }
        if decision is not None:
            key = f"approval-decision:{sid}:{decision['approval_event_id']}"
            prior = c.execute(
                "SELECT event_id FROM session_events WHERE deployment_namespace=%s "
                "AND session_id=%s AND idempotency_key=%s",
                (ns, sid, key),
            ).fetchone()
            digest = sha256(
                json.dumps(decision, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if prior:
                event = _bounded_event(c, ns, prior["event_id"])
                if event.payload.get("decision_fingerprint") != digest:
                    raise ValueError("approval_decision_conflict")
                return {"decision": decision["decision"], "run_id": run_id, "replayed": True}
        row = c.execute(
            "SELECT event_id,octet_length(payload::text) AS bytes FROM session_events "
            "WHERE deployment_namespace=%s AND session_id=%s AND sequence=%s "
            "AND event_type='approval_requested'",
            (ns, sid, head["current_version"]),
        ).fetchone()
        if row is None or row["bytes"] > 1_048_576:
            raise ValueError("approval_not_pending")
        event = _bounded_event(c, ns, row["event_id"])
        session = get_session_in_transaction(c, ns, sid)
        context = session.approval_context if session else None
        if (
            session is None
            or context is None
            or session.status.value != "waiting_approval"
            or session.current_sequence != event.sequence
            or context.tool_call_id != event.payload.get("tool_call_id")
            or context.call_fingerprint != event.payload.get("call_fingerprint")
        ):
            raise ValueError("approval_projection_not_ready")
        view = {
            "approval_event_id": str(event.event_id),
            "expected_revision": event.sequence,
            "tool_call_id": context.tool_call_id,
            "call_fingerprint": context.call_fingerprint,
            "run_id": run_id,
            "tool_name": context.tool_name,
            "reason": context.reason,
            "arguments": context.arguments,
            "status": "awaiting_approval",
        }
        if not context.call_fingerprint or not context.tool_call_id:
            raise ValueError("approval_identity_missing")
        if decision is None:
            return view
        if any(
            decision[k] != view[k]
            for k in (
                "approval_event_id",
                "expected_revision",
                "tool_call_id",
                "call_fingerprint",
                "run_id",
            )
        ):
            raise ValueError("approval_identity_changed")
        active = c.execute(
            "SELECT 1 FROM worker_leases l JOIN control_plane_epochs e "
            "USING(deployment_namespace) WHERE l.deployment_namespace=%s "
            "AND l.session_id=%s AND l.control_plane_epoch=e.epoch "
            "AND l.released_at IS NULL AND l.expires_at>clock_timestamp()",
            (ns, sid),
        ).fetchone()
        if active:
            raise ValueError("approval_worker_busy")
        granted = decision["decision"] == "approve"
        result = ApprovalDecisionService().build_event(
            session=session,
            next_sequence=event.sequence + 1,
            command=ApprovalDecisionCommand(
                action=ApprovalDecisionAction.GRANT if granted else ApprovalDecisionAction.REJECT,
                operator=decision["operator"],
                reason="Explicit user approval" if granted else "Explicit user rejection",
            ),
        )
        result = result.model_copy(
            update={
                "idempotency_key": key,
                "payload": {
                    **result.payload,
                    "decision_fingerprint": digest,
                    "approval_event_id": str(event.event_id),
                    "run_id": run_id,
                },
            }
        )
        append_event_in_transaction(c, ns, result)
        save_session_in_transaction(c, ns, apply_event(session, result))
        workspace = get_workspace_in_transaction(c, ns, sid)
        if workspace is not None:
            save_workspace_in_transaction(c, ns, apply_workspace(workspace, result))
        if granted:
            # Internal wakeup inherits the original anchor and active Turn snapshot.
            command = SessionCommand(
                command_id=uuid5(NAMESPACE_URL, key + ":resume"),
                session_id=sid,
                kind=SessionCommandKind.RESUME,
                expected_revision=result.sequence,
                idempotency_key="approval-resume:" + key,
                payload={},
            )
            resume = SessionEvent.create(
                session_id=sid,
                sequence=result.sequence + 1,
                event_type=EventType.SESSION_COMMAND_ACCEPTED,
                actor=EventActor.HARNESS,
                idempotency_key=command.idempotency_key,
                payload=command.event_payload(),
            )
            # Native appender atomically writes command wakeup/outbox. No broker I/O here.
            append_event_in_transaction(c, ns, resume)
        return {"decision": decision["decision"], "run_id": run_id, "replayed": False}


def _bounded_event(c: Any, ns: str, event_id: Any) -> SessionEvent:
    size = c.execute(
        "SELECT octet_length(payload::text) AS bytes FROM session_events "
        "WHERE deployment_namespace=%s AND event_id=%s",
        (ns, event_id),
    ).fetchone()
    if size is None or size["bytes"] > 1_048_576:
        raise ValueError("approval_event_unavailable")
    event = read_event_in_transaction(c, ns, event_id)
    if event is None:
        raise ValueError("approval_event_unavailable")
    return event
