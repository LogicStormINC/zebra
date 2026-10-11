"""Bounded observation fields, without full Turn, usage or attachment hydration."""

from agent_core.domain.identifiers import TaskId
from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.task_responses import task_not_found


def task_header(stores: ControlPlaneStores, task_id: TaskId) -> ApiResponse:
    header = stores.tasks.read_task_header(task_id)
    if header is None:
        return task_not_found(str(task_id))
    if header.title is None or header.status is None or header.active_segment_sequence is None:
        return ApiResponse(409, {"task_id": str(task_id), "status": "projection_incomplete"})
    body = {
        "task_id": str(task_id),
        "session_id": str(task_id),
        "active_segment_id": str(header.active_segment_id),
        "current_sequence": header.current_sequence,
        "active_segment_sequence": header.active_segment_sequence,
        "title": header.title,
        "title_truncated": header.title_truncated,
        "status": header.status.value,
        "clarification_context": (
            {"clarification_id": header.clarification_id} if header.clarification_id else None
        ),
        "clarification_unavailable": header.clarification_invalid,
    }
    return ApiResponse(200, body)
