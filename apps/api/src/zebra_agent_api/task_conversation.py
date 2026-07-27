from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_core.application.public_conversation import project_public_conversation
from agent_storage import SQLiteAgentTaskStore

from zebra_agent_api.responses import ApiResponse, bad_request
from zebra_agent_api.task_api import parse_task_id


@dataclass(frozen=True)
class TaskConversationReadApi:
    database_path: Path

    def get(self, task_id: str, query: Mapping[str, str]) -> ApiResponse:
        parsed_task_id = parse_task_id(task_id)
        if isinstance(parsed_task_id, ApiResponse):
            return parsed_task_id
        after_sequence = _parse_after_sequence(query.get("after_sequence"))
        if isinstance(after_sequence, ApiResponse):
            return after_sequence
        store = SQLiteAgentTaskStore(self.database_path)
        if store.get_task(parsed_task_id) is None:
            return ApiResponse(
                status_code=404,
                body={"task_id": task_id, "status": "not_found"},
            )
        projection = project_public_conversation(
            parsed_task_id,
            store.read_events(parsed_task_id, -1),
            after_sequence=after_sequence,
        )
        return ApiResponse(status_code=200, body=projection.to_dict())


def _parse_after_sequence(value: str | None) -> int | ApiResponse:
    if value is None:
        return -1
    try:
        parsed = int(value)
    except ValueError:
        return bad_request("after_sequence must be an integer")
    if parsed < -1:
        return bad_request("after_sequence must be greater than or equal to -1")
    return parsed
