"""Original-message surface condition inside the existing fenced PostgreSQL work unit."""

from typing import Any
from uuid import UUID

from agent_core.domain.identifiers import TaskId

from agent_storage.idempotency import new_idempotency_record
from agent_storage.postgres.task_event_positions import _lock_task
from agent_storage.postgres.work_unit import borrow_work_unit

CONSUMED = "client-message-surface-v1-consumed"


def lock_message_anchor(
    store: Any,
    *,
    task: str,
    run_id: str,
    receipt_key: str,
    request_hash: str,
    event_id: str,
    segment_id: str,
    segment_sequence: int,
) -> str | None:
    database = store._database
    namespace = database.deployment_namespace
    unit = borrow_work_unit((database._dsn, namespace))
    if unit is None:
        raise RuntimeError("message condition requires the enclosing atomic transaction")
    with unit as connection:
        # Match append/Handoff: member stream before Task61. Never lock a foreign stream.
        stream = connection.execute(
            "SELECT s.current_version,e.event_position_source_ready "
            "FROM session_streams s JOIN execution_segments e "
            "ON e.deployment_namespace=s.deployment_namespace AND e.session_id=s.session_id "
            "WHERE s.deployment_namespace=%s AND s.session_id=%s AND e.task_id=%s FOR UPDATE OF s",
            (namespace, UUID(segment_id), UUID(task)),
        ).fetchone()
        if stream is None:
            return "message_segment_not_in_task"
        _lock_task(connection, namespace, TaskId(UUID(task)))
        current = connection.execute(
            "SELECT active_segment_id,event_position_state FROM agent_tasks "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (namespace, UUID(task)),
        ).fetchone()
        if current is None or str(current["active_segment_id"]) != segment_id:
            return "message_segment_not_active"
        if current["event_position_state"] != "ready" or not stream["event_position_source_ready"]:
            return "message_source_not_ready"
        if stream["current_version"] != segment_sequence:
            return "message_source_advanced"
        receipt = store.get(action=f"task-message:{task}", idempotency_key=receipt_key)
        if receipt is None or receipt.request_hash != request_hash or receipt.status_code != 201:
            return "original_message_receipt_unavailable"
        body = receipt.response_body
        expected = {
            "event_id": event_id,
            "segment_id": segment_id,
            "segment_sequence": segment_sequence,
        }
        coordinates = body.get("message_coordinates")
        if (
            body.get("appended") is not True
            or body.get("task_id") != task
            or body.get("session_id") != task
            or not isinstance(coordinates, dict)
            or coordinates != expected
            or type(coordinates.get("segment_sequence")) is not int
            or type(body.get("sequence")) is not int
            or body["sequence"] != segment_sequence
            or type(body.get("current_sequence")) is not int
            or body["current_sequence"] != segment_sequence
        ):
            return "original_message_coordinates_unavailable"
        source = connection.execute(
            "SELECT payload,actor FROM session_events WHERE deployment_namespace=%s "
            "AND task_id=%s AND event_id=%s AND session_id=%s AND sequence=%s "
            "AND event_type='user_message_received'",
            (namespace, UUID(task), UUID(event_id), UUID(segment_id), segment_sequence),
        ).fetchone()
        if (
            source is None
            or source["actor"] != "user"
            or source["payload"].get("origin") != "human"
            or not isinstance(body.get("content"), str)
            or source["payload"].get("content") != body["content"].strip()
        ):
            return "original_message_source_mismatch"
        if (
            connection.execute(
                "SELECT 1 FROM client_run_bindings WHERE deployment_namespace=%s "
                "AND task_id=%s AND run_id=%s LIMIT 1",
                (namespace, UUID(task), run_id),
            ).fetchone()
            is not None
        ):
            return "message_run_already_bound"
        if store.get(action=CONSUMED, idempotency_key=f"{task}:{event_id}") is not None:
            return "original_message_already_consumed"
        return None


def consume_message_anchor(
    store: Any, *, task: str, event_id: str, scoped: str, digest: str, run: str
) -> None:
    database = store._database
    if borrow_work_unit((database._dsn, database.deployment_namespace)) is None:
        raise RuntimeError("message consumption requires the enclosing atomic transaction")
    store.save(
        new_idempotency_record(
            action=CONSUMED,
            idempotency_key=f"{task}:{event_id}",
            request_hash=digest,
            status_code=201,
            response_body={"admission": scoped, "run": run, "event_id": event_id},
        )
    )
