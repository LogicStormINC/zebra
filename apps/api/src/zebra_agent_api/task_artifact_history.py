"""Bounded historical Artifact coordinates; Task authorization remains upstream."""

from collections.abc import Callable
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse, bad_request
from zebra_agent_api.task_api import parse_task_id
from zebra_agent_api.task_responses import task_not_found


def artifact_segments(
    stores: ControlPlaneStores, task_id: str, query: dict[str, str]
) -> ApiResponse:
    parsed = parse_task_id(task_id)
    if isinstance(parsed, ApiResponse):
        return parsed
    try:
        after = int(query.get("after", "-1"))
        limit = int(query.get("limit", "50"))
        if after < -1 or not 1 <= limit <= 100:
            raise ValueError
    except (TypeError, ValueError):
        return bad_request("invalid artifact segment page")
    task = stores.tasks.get_task(parsed)
    if task is None:
        return task_not_found(task_id)
    page = stores.tasks.segment_page(parsed, after_index=after, limit=limit + 1)
    return ApiResponse(
        200,
        {
            "task_id": task_id,
            "active_segment_id": str(task.active_segment_id),
            "segments": [
                {"segment_id": str(item.session_id), "segment_index": item.segment_index}
                for item in page[:limit]
            ],
            "has_more": len(page) > limit,
            "next_after": page[limit - 1].segment_index if len(page) > limit else None,
        },
    )


def route_task_artifact(
    stores: ControlPlaneStores,
    task_id: str,
    query: dict[str, str],
    handler: Callable[[str], ApiResponse],
) -> ApiResponse:
    parsed = parse_task_id(task_id)
    if isinstance(parsed, ApiResponse):
        return parsed
    selected = query.get("segment_id")
    if selected is None:
        segment_id = stores.tasks.active_segment(parsed)
    else:
        try:
            segment_id = SessionId(UUID(selected))
        except (TypeError, ValueError):
            return bad_request("invalid Artifact segment")
        # Primary indexed membership only; never list/replay a long Task to authorize.
        if stores.tasks.task_id_for_session(segment_id) != parsed:
            return task_not_found(task_id)
    if segment_id is None:
        return task_not_found(task_id)
    response = handler(str(segment_id))
    body = dict(response.body)
    body.update(task_id=task_id, session_id=task_id, source_segment_id=str(segment_id))
    return ApiResponse(response.status_code, body)
