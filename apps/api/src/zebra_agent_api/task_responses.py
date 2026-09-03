"""Shared Task API response shapes."""

from zebra_agent_api.responses import ApiResponse

DEFAULT_TASK_LIMIT = 50
MAX_TASK_LIMIT = 100


def parse_task_limit(raw: str | None) -> int | ApiResponse:
    try:
        limit = DEFAULT_TASK_LIMIT if raw is None else int(raw)
    except ValueError:
        limit = 0
    if 1 <= limit <= MAX_TASK_LIMIT:
        return limit
    return ApiResponse(
        400,
        {"status": "invalid_request", "reason": "limit must be an integer between 1 and 100"},
    )


def task_not_found(task_id: str) -> ApiResponse:
    return ApiResponse(404, {"task_id": task_id, "status": "not_found"})
