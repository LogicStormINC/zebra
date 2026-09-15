"""Small serialization and request helpers for the Task Schedule API."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskScheduleId
from agent_core.domain.task_bindings import host_context_digest
from agent_core.domain.task_schedule_authority import (
    ScheduleAuthorityBinding,
    ScheduledTaskTemplate,
    ScheduleOwner,
)
from agent_core.domain.task_schedules import TaskSchedule, TaskScheduleFiring

from zebra_agent_api.responses import ApiResponse, bad_request

if TYPE_CHECKING:
    from zebra_agent_api.routes import RouteRequest


def build_schedule_authority(
    context: HostContextEnvelope,
    owner: ScheduleOwner,
    schedule_id: TaskScheduleId,
    *,
    template: ScheduledTaskTemplate,
    definition_digest: str,
    bound_at: datetime,
) -> ScheduleAuthorityBinding:
    return ScheduleAuthorityBinding(
        binding_id=uuid4(),
        schedule_id=schedule_id,
        owner=owner,
        host_context=context,
        host_capability_digest=host_context_digest(context),
        agent_definition_digest=definition_digest,
        policy_digest=_digest({"policy_version": context.policy_version, "task": template.payload}),
        extension_snapshot_digest=_digest(
            {
                key: template.payload.get(key)
                for key in (
                    "skill_components",
                    "mcp_allowlist",
                    "mcp_resource_ids",
                    "mcp_prompt_id",
                )
            }
        ),
        binding_revision=1,
        bound_at=bound_at,
    )


def schedule_body(schedule: TaskSchedule) -> dict[str, object]:
    body = schedule.model_dump(mode="json")
    body["task_template"] = schedule.task_template.payload
    body["schedule_id"] = str(schedule.schedule_id)
    return body


def firing_body(firing: TaskScheduleFiring) -> dict[str, object]:
    task_id = str(firing.task_id) if firing.task_id is not None else None
    return {
        "fire_id": str(firing.fire_id),
        "schedule_id": str(firing.schedule_id),
        "schedule_version": firing.schedule_version,
        "scheduled_for": firing.scheduled_for.isoformat(),
        "status": firing.status.value,
        "task_id": task_id,
        "task_url": f"/tasks/{task_id}" if task_id is not None else None,
        "attempt": firing.attempt,
        "failure_code": firing.failure_code,
        "created_at": firing.created_at.isoformat(),
        "dispatched_at": firing.dispatched_at.isoformat() if firing.dispatched_at else None,
        "completed_at": firing.completed_at.isoformat() if firing.completed_at else None,
    }


def schedule_path(path: str) -> tuple[TaskScheduleId, tuple[str, ...]] | ApiResponse:
    parts = tuple(part for part in path.removeprefix("/schedules/").split("/") if part)
    if not parts:
        return bad_request("schedule_id is required")
    try:
        schedule_id = TaskScheduleId(UUID(parts[0]))
    except ValueError:
        return bad_request("schedule_id must be a UUID")
    return schedule_id, parts[1:]


def expected_version(request: RouteRequest, body: dict[str, object]) -> int | ApiResponse:
    raw: object = body.get("schedule_version")
    if raw is None:
        raw = (request.headers or {}).get("if-match") or (request.headers or {}).get("If-Match")
        if isinstance(raw, str):
            raw = raw.strip().removeprefix("W/").strip('"')
    if isinstance(raw, bool) or not isinstance(raw, int | str):
        return bad_request("schedule_version or If-Match is required")
    try:
        value = int(raw)
    except ValueError:
        return bad_request("schedule version must be a positive integer")
    return value if value > 0 else bad_request("schedule version must be a positive integer")


def request_limit(request: RouteRequest, *, default: int) -> int:
    raw = (request.query or {}).get("limit")
    value = default if raw is None else int(raw)
    if value < 1 or value > 200:
        raise ValueError("limit must be between 1 and 200")
    return value


def idempotency_key(request: RouteRequest) -> str | None:
    headers = request.headers or {}
    raw = headers.get("idempotency-key") or headers.get("Idempotency-Key")
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
