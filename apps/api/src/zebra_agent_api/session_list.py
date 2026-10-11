from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast

from agent_core.domain.identifiers import TaskId
from agent_core.domain.sessions import SessionStatus
from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_summary import serialize_session_summary
from zebra_agent_api.task_api import TaskReadApi
from zebra_agent_api.task_responses import parse_task_limit


@dataclass(frozen=True)
class SessionListApi:
    stores: ControlPlaneStores

    def list_sessions(
        self,
        query: Mapping[str, str],
        *,
        authorize_task: Callable[[TaskId], ApiResponse | None] | None = None,
        include_tasks: bool = False,
    ) -> ApiResponse:
        if authorize_task is not None:
            limit = parse_task_limit(query.get("limit"))
            if isinstance(limit, ApiResponse):
                return limit
            items = []
            # ponytail: bounded recent candidate page, not an exhaustive Host
            # inventory. A later indexed Host-thread page can avoid underfill.
            for task in self.stores.tasks.list_tasks(limit=limit):
                denied = authorize_task(task.task_id)
                if denied is not None:
                    if denied.status_code == 404:
                        continue
                    return denied
                session = self.stores.sessions.get_session(task.active_segment_id)
                if session is None:
                    continue
                item = serialize_session_summary(
                    session,
                    self.stores.workspaces.get_workspace(task.active_segment_id),
                    include_timestamps=True,
                )
                item.update(
                    session_id=str(task.task_id),
                    current_sequence=task.current_sequence,
                    status=task.status.value,
                    task_status=task.status.value
                    if task.status
                    in {
                        SessionStatus.COMPLETED,
                        SessionStatus.FAILED,
                        SessionStatus.CANCELLED,
                    }
                    else "open",
                )
                if include_tasks:
                    item["task_id"] = str(task.task_id)
                items.append(item)
            body: dict[str, object] = {"sessions": items, "count": len(items), "limit": limit}
            if include_tasks:
                body["tasks"] = items
            return ApiResponse(200, body)
        response = TaskReadApi(self.stores).list(query)
        if response.status_code != 200:
            return response
        body = dict(response.body)
        if not include_tasks:
            body.pop("tasks", None)
        sessions = cast(list[dict[str, object]], body["sessions"])
        body["sessions"] = (
            sessions
            if include_tasks
            else [
                {key: value for key, value in item.items() if key != "task_id"} for item in sessions
            ]
        )
        return ApiResponse(response.status_code, body)
