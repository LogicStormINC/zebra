import json
import sqlite3
from typing import Any

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.plans import SessionPlan
from agent_core.ports.session_handoff import HandoffOperation, SessionHandoffCommitRequest


def build_handoff_events(
    operation: HandoffOperation,
    request: SessionHandoffCommitRequest,
    workspace: sqlite3.Row,
    *,
    model_id: str | None = None,
) -> tuple[SessionEvent, ...]:
    envelope = request.envelope
    parent = SessionEvent.create(
        session_id=operation.source_session_id,
        sequence=operation.expected_source_stream_version + 1,
        event_type=EventType.SESSION_HANDOFF_COMMITTED,
        actor=EventActor.SYSTEM,
        idempotency_key=f"handoff:{operation.idempotency_key_hash}",
        created_at=envelope.created_at,
        payload={
            "handoff_id": str(operation.handoff_id),
            "target_session_id": str(operation.target_session_id),
            "reason": request.create_request.reason.value,
            "target_stage_index": envelope.target_stage_index,
            "source_event_range": envelope.source_event_range.model_dump(),
            "source_event_hash": envelope.source_event_hash,
            "artifact_id": request.artifact_id,
            "checksum": envelope.checksum,
            "idempotency_key_hash": operation.idempotency_key_hash,
        },
    )
    child_payloads: tuple[tuple[EventType, EventActor, dict[str, Any]], ...] = (
        (EventType.SESSION_CREATED, EventActor.SYSTEM, {"title": request.create_request.title}),
        (
            EventType.SESSION_HANDOFF_RECEIVED,
            EventActor.SYSTEM,
            {
                "parent_session_id": str(operation.source_session_id),
                "root_session_id": str(envelope.root_session_id),
                "handoff_id": str(operation.handoff_id),
                "stage_index": envelope.target_stage_index,
                "artifact_id": request.artifact_id,
                "checksum": envelope.checksum,
            },
        ),
        (
            EventType.USER_MESSAGE_RECEIVED,
            EventActor.USER,
            {
                "content": request.create_request.stage_prompt,
                "source": "session_handoff",
                "handoff_id": str(operation.handoff_id),
                "principal_identity_hash": request.create_request.principal_identity_hash,
                "actor_kind": request.create_request.actor_kind.value,
                "trust": request.create_request.actor_kind.value,
            },
        ),
        (
            EventType.TASK_PREPARED,
            EventActor.HARNESS,
            {
                "title": request.create_request.title,
                "user_input": request.create_request.stage_prompt,
                "workspace_root": workspace["workspace_root"],
                "policy_profile": workspace["policy_profile"],
                "tool_profile": workspace["tool_profile"],
                "network_profile": workspace["network_profile"],
                "network_allowlist": json.loads(workspace["network_allowlist"]),
                "mcp_allowlist": (
                    None
                    if workspace["mcp_allowlist"] is None
                    else json.loads(workspace["mcp_allowlist"])
                ),
                "preapproved_readonly_tools": (
                    None
                    if workspace["preapproved_readonly_tools"] is None
                    else json.loads(workspace["preapproved_readonly_tools"])
                ),
                "skill_components": (
                    None
                    if workspace["skill_components"] is None
                    else json.loads(workspace["skill_components"])
                ),
                "skill_component_identities": (
                    None
                    if workspace["skill_component_identities"] is None
                    else json.loads(workspace["skill_component_identities"])
                ),
                "agent_definition": (
                    None
                    if workspace["agent_definition"] is None
                    else json.loads(workspace["agent_definition"])
                ),
                **({"model_id": model_id} if model_id is not None else {}),
            },
        ),
    )
    child_events = tuple(
        SessionEvent.create(
            session_id=operation.target_session_id,
            sequence=sequence,
            event_type=event_type,
            actor=actor,
            payload=payload,
            idempotency_key=f"handoff:{operation.handoff_id}:{sequence}",
            created_at=envelope.created_at,
        )
        for sequence, (event_type, actor, payload) in enumerate(child_payloads)
    )
    return (parent, *child_events)


def insert_child_projections(
    connection: sqlite3.Connection,
    operation: HandoffOperation,
    request: SessionHandoffCommitRequest,
    workspace: sqlite3.Row,
) -> None:
    created_at = request.envelope.created_at.isoformat()
    task_plan_json = _latest_task_plan_json(connection, operation.source_session_id)
    connection.execute(
        "INSERT INTO session_projections VALUES (?, ?, 'ready', ?, ?, 3, NULL, NULL, ?)",
        (
            str(operation.target_session_id),
            request.create_request.title,
            created_at,
            created_at,
            task_plan_json,
        ),
    )
    columns = [row[1] for row in connection.execute("PRAGMA table_info(workspace_projections)")]
    values = [workspace[column] for column in columns]
    values[columns.index("session_id")] = str(operation.target_session_id)
    values[columns.index("updated_at")] = created_at
    values[columns.index("current_sequence")] = 3
    placeholders = ", ".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO workspace_projections ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )


def _latest_task_plan_json(
    connection: sqlite3.Connection,
    source_session_id: object,
) -> str:
    row = connection.execute(
        """
        SELECT e.payload, e.created_at
        FROM session_events e
        JOIN session_lineage l ON l.session_id = e.session_id
        WHERE l.root_session_id = (
            SELECT root_session_id FROM session_lineage WHERE session_id = ?
        ) AND e.event_type = ?
        ORDER BY l.stage_index DESC, e.sequence DESC
        LIMIT 1
        """,
        (str(source_session_id), EventType.PLAN_UPDATED.value),
    ).fetchone()
    if row is None:
        return json.dumps(SessionPlan().model_dump(mode="json"))
    payload = json.loads(row["payload"])
    plan = SessionPlan.model_validate(
        {"steps": payload.get("steps", ()), "updated_at": row["created_at"]}
    )
    return json.dumps(plan.model_dump(mode="json"))
