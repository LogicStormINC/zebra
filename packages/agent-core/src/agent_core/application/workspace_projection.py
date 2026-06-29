from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus


class WorkspaceProjectionError(ValueError):
    """Raised when a workspace projection cannot be rebuilt from events."""


def rebuild_workspace(events: list[SessionEvent]) -> WorkspaceProjection:
    prepared_event = next(
        (event for event in events if event.event_type is EventType.TASK_PREPARED),
        None,
    )
    if prepared_event is None:
        raise WorkspaceProjectionError("event stream does not contain task_prepared")

    workspace_root = _required_payload_string(prepared_event, "workspace_root")
    projection = WorkspaceProjection(
        session_id=prepared_event.session_id,
        workspace_root=workspace_root,
        prepared_at=prepared_event.created_at,
        updated_at=prepared_event.created_at,
        current_sequence=prepared_event.sequence,
        status=WorkspaceStatus.PREPARED,
        policy_profile=_optional_payload_string(prepared_event, "policy_profile"),
    )
    for event in events:
        if event.sequence < prepared_event.sequence:
            continue
        projection = apply_event(projection, event)
    return projection


def apply_event(
    projection: WorkspaceProjection,
    event: SessionEvent,
) -> WorkspaceProjection:
    if event.session_id != projection.session_id:
        raise WorkspaceProjectionError(
            "event session_id does not match workspace projection session_id"
        )
    if event.sequence < projection.current_sequence:
        return projection

    updates: dict[str, object] = {
        "updated_at": event.created_at,
        "current_sequence": event.sequence,
    }
    next_status = _next_status_for_event(event)
    if next_status is not None:
        updates["status"] = next_status
    attempt_number = _optional_attempt_number(event)
    if attempt_number is not None:
        updates["last_attempt_number"] = attempt_number
    if event.event_type is EventType.TASK_PREPARED:
        updates["policy_profile"] = _optional_payload_string(event, "policy_profile")
    return projection.model_copy(update=updates)


def _next_status_for_event(event: SessionEvent) -> WorkspaceStatus | None:
    status_map: dict[EventType, WorkspaceStatus] = {
        EventType.TASK_PREPARED: WorkspaceStatus.PREPARED,
        EventType.HARNESS_ATTEMPT_STARTED: WorkspaceStatus.RUNNING,
        EventType.MODEL_REQUEST_STARTED: WorkspaceStatus.RUNNING,
        EventType.PLAN_PROPOSED: WorkspaceStatus.RUNNING,
        EventType.PLAN_APPROVED: WorkspaceStatus.RUNNING,
        EventType.TOOL_CALL_PROPOSED: WorkspaceStatus.RUNNING,
        EventType.TOOL_EXECUTION_STARTED: WorkspaceStatus.RUNNING,
        EventType.APPROVAL_REQUESTED: WorkspaceStatus.WAITING_APPROVAL,
        EventType.APPROVAL_GRANTED: WorkspaceStatus.RUNNING,
        EventType.APPROVAL_REJECTED: WorkspaceStatus.FAILED,
        EventType.SESSION_COMPLETED: WorkspaceStatus.COMPLETED,
        EventType.SESSION_FAILED: WorkspaceStatus.FAILED,
        EventType.SESSION_CANCELLED: WorkspaceStatus.CANCELLED,
    }
    return status_map.get(event.event_type)


def _required_payload_string(event: SessionEvent, key: str) -> str:
    value = _optional_payload_string(event, key)
    if value is None:
        raise WorkspaceProjectionError(f"{event.event_type.value} must include {key}")
    return value


def _optional_payload_string(event: SessionEvent, key: str) -> str | None:
    value = event.payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _optional_attempt_number(event: SessionEvent) -> int | None:
    value = event.payload.get("attempt_number")
    if isinstance(value, int) and value > 0:
        return value
    return None
