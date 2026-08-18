from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.task_api import TaskReadApi

DEFAULT_SESSION_LIMIT = 50
MAX_SESSION_LIMIT = 100


@dataclass(frozen=True)
class SessionListApi:
    stores: ControlPlaneStores

    def list_sessions(self, query: Mapping[str, str]) -> ApiResponse:
        response = TaskReadApi(self.stores).list(query)
        if response.status_code != 200:
            return response
        body = dict(response.body)
        body.pop("tasks", None)
        sessions = cast(list[dict[str, object]], body["sessions"])
        body["sessions"] = [
            {key: value for key, value in item.items() if key != "task_id"} for item in sessions
        ]
        return ApiResponse(response.status_code, body)


def _parse_limit(raw: str | None) -> int | ApiResponse:
    if raw is None:
        return DEFAULT_SESSION_LIMIT
    try:
        limit = int(raw)
    except ValueError:
        limit = 0
    if 1 <= limit <= MAX_SESSION_LIMIT:
        return limit
    return ApiResponse(
        status_code=400,
        body={
            "status": "invalid_request",
            "reason": f"limit must be an integer between 1 and {MAX_SESSION_LIMIT}",
        },
    )
