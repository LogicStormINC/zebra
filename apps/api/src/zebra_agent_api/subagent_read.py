"""Read-only parent/child Task projection for operators and Host UIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.task_api import parse_task_id
from zebra_agent_api.task_responses import task_not_found


@dataclass(frozen=True)
class SubagentReadApi:
    stores: ControlPlaneStores

    def list_for_parent(self, task_id: str) -> ApiResponse:
        parent_id = parse_task_id(task_id)
        if isinstance(parent_id, ApiResponse):
            return parent_id
        if self.stores.tasks.get_task(parent_id) is None:
            return task_not_found(task_id)

        items: dict[str, dict[str, object]] = {}
        for record in self.stores.tasks.read_events(parent_id, -1):
            event = record.event
            if event.event_type is EventType.SUBAGENT_DELEGATED:
                child_id = _text(event.payload, "child_task_id")
                if child_id is None:
                    continue
                arguments = event.payload.get("arguments")
                details = arguments if isinstance(arguments, dict) else {}
                items[child_id] = {
                    "child_task_id": child_id,
                    "created_at": event.created_at.isoformat(),
                    "delegation_reason": _text(details, "delegation_reason"),
                    "objective": _text(details, "objective"),
                    "parent_task_id": task_id,
                    "status": _task_status(self.stores, child_id) or "running",
                }
            elif event.event_type is EventType.SESSION_COMMAND_ACCEPTED:
                _apply_terminal_results(items, event.payload)
        return ApiResponse(
            200,
            {"count": len(items), "subagents": list(items.values()), "task_id": task_id},
        )


def _apply_terminal_results(items: dict[str, dict[str, object]], payload: dict[str, Any]) -> None:
    command_payload = payload.get("payload")
    results = command_payload.get("child_results") if isinstance(command_payload, dict) else None
    if not isinstance(results, list):
        return
    for result in results:
        if not isinstance(result, dict):
            continue
        child_id = _text(result, "child_task_id")
        status = _text(result, "status")
        if child_id in items and status is not None:
            items[child_id]["status"] = status


def _task_status(stores: ControlPlaneStores, child_task_id: str) -> str | None:
    try:
        child = stores.tasks.get_task(TaskId(UUID(child_task_id)))
    except ValueError:
        return None
    return child.status.value if child is not None else None


def _text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None
