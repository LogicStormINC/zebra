from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.networking import NetworkProfileName
from agent_core.domain.tool_profiles import ToolProfile
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
        tool_profile=_tool_profile_from_event(prepared_event),
        network_profile=NetworkProfileName(
            _optional_payload_string(prepared_event, "network_profile") or "none"
        ),
        network_allowlist=_network_allowlist_from_event(prepared_event),
        mcp_allowlist=_mcp_allowlist_from_event(prepared_event),
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
        updates["tool_profile"] = _tool_profile_from_event(event)
        updates["network_profile"] = NetworkProfileName(
            _optional_payload_string(event, "network_profile") or "none"
        )
        updates["network_allowlist"] = _network_allowlist_from_event(event)
        updates["mcp_allowlist"] = _mcp_allowlist_from_event(event)
    if event.event_type is EventType.RUNTIME_PROVISIONED:
        updates["runtime_name"] = _required_payload_string(event, "runtime_class")
        updates["runtime_engine"] = _required_payload_string(event, "engine")
        updates["runtime_image"] = _optional_payload_string(event, "image")
        updates["runtime_spec_digest"] = _required_payload_string(
            event, "spec_digest"
        )
        updates["runtime_network_enforcement"] = _required_payload_string(
            event, "network_enforcement"
        )
        updates["runtime_workspace_writable"] = event.payload.get(
            "workspace_writable"
        )
    if event.event_type is EventType.SESSION_SUSPENDED:
        snapshot_id = _optional_payload_string(event, "snapshot_id")
        if snapshot_id is not None:
            updates["runtime_name"] = _required_payload_string(event, "runtime_name")
            updates["snapshot_id"] = snapshot_id
            updates["snapshot_path"] = _required_payload_string(event, "snapshot_path")
    if event.event_type is EventType.SESSION_RESUMED:
        updates["workspace_root"] = _required_payload_string(event, "workspace_root")
        updates["runtime_name"] = _required_payload_string(event, "runtime_name")
        updates["snapshot_id"] = None
        updates["snapshot_path"] = None
    return projection.model_copy(update=updates)


def _next_status_for_event(event: SessionEvent) -> WorkspaceStatus | None:
    status_map: dict[EventType, WorkspaceStatus] = {
        EventType.TASK_PREPARED: WorkspaceStatus.PREPARED,
        EventType.HARNESS_ATTEMPT_STARTED: WorkspaceStatus.RUNNING,
        EventType.MODEL_REQUEST_STARTED: WorkspaceStatus.RUNNING,
        EventType.MODEL_RESPONSE_DELTA: WorkspaceStatus.RUNNING,
        EventType.PLAN_PROPOSED: WorkspaceStatus.RUNNING,
        EventType.PLAN_APPROVED: WorkspaceStatus.RUNNING,
        EventType.TOOL_CALL_PROPOSED: WorkspaceStatus.RUNNING,
        EventType.TOOL_EXECUTION_STARTED: WorkspaceStatus.RUNNING,
        EventType.APPROVAL_REQUESTED: WorkspaceStatus.WAITING_APPROVAL,
        EventType.APPROVAL_GRANTED: WorkspaceStatus.RUNNING,
        EventType.APPROVAL_REJECTED: WorkspaceStatus.FAILED,
        EventType.SESSION_SUSPENDED: WorkspaceStatus.SUSPENDED,
        EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED: WorkspaceStatus.SUSPENDED,
        EventType.SESSION_RESUMED: WorkspaceStatus.PREPARED,
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


def _tool_profile_from_event(event: SessionEvent) -> ToolProfile:
    value = _optional_payload_string(event, "tool_profile")
    if value is None:
        return ToolProfile.CODING
    try:
        return ToolProfile(value)
    except ValueError as exc:
        raise WorkspaceProjectionError("task_prepared contains unsupported tool_profile") from exc


def _network_allowlist_from_event(event: SessionEvent) -> tuple[str, ...]:
    value = event.payload.get("network_allowlist")
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise WorkspaceProjectionError("task_prepared contains invalid network_allowlist")
    return tuple(item.strip() for item in value)


def _mcp_allowlist_from_event(event: SessionEvent) -> tuple[str, ...] | None:
    if "mcp_allowlist" not in event.payload:
        return None
    value = event.payload["mcp_allowlist"]
    if value is None:
        return None
    if not isinstance(value, list):
        raise WorkspaceProjectionError("task_prepared contains invalid mcp_allowlist")
    try:
        return normalize_mcp_allowlist(value)
    except ValueError as exc:
        raise WorkspaceProjectionError("task_prepared contains invalid mcp_allowlist") from exc


def _optional_attempt_number(event: SessionEvent) -> int | None:
    value = event.payload.get("attempt_number")
    if isinstance(value, int) and value > 0:
        return value
    return None
