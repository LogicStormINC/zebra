"""A keyed create has one owner-scoped identity even if its HTTP ACK is lost."""

import json
import re
from uuid import NAMESPACE_URL, uuid5

from agent_core.domain.identifiers import TaskScheduleId, new_task_schedule_id
from agent_core.domain.task_schedule_authority import ScheduledTaskTemplate, ScheduleOwner
from agent_core.domain.task_schedules import (
    ScheduleMisfirePolicy,
    ScheduleOverlapPolicy,
    ScheduleTrigger,
    TaskScheduleStatus,
)
from agent_core.ports.task_schedules import TaskScheduleStorePort

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.task_schedule_api_support import schedule_body


def create_identity(owner: ScheduleOwner, key: str | None) -> TaskScheduleId:
    if key is None:
        return new_task_schedule_id()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}", key) is None:
        raise ValueError("invalid Schedule create idempotency key")
    scope = json.dumps(owner.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return TaskScheduleId(uuid5(NAMESPACE_URL, "zebra:schedule:create:v1:" + scope + "\0" + key))


def replay_create(
    store: TaskScheduleStorePort,
    owner: ScheduleOwner,
    identity: TaskScheduleId,
    body: dict[str, object],
    template: ScheduledTaskTemplate,
    trigger: ScheduleTrigger,
) -> ApiResponse | None:
    existing = store.get(identity, owner=owner)
    if existing is None:
        return None
    expected = {
        "title": body.get("title", template.payload.get("title", template.payload["prompt"])),
        "timezone": str(body.get("timezone", "UTC")),
        "trigger": trigger,
        "task_template": template,
        "misfire_policy": body.get("misfire_policy", ScheduleMisfirePolicy.COALESCE_ONE),
        "misfire_grace_seconds": body.get("misfire_grace_seconds", 3600),
        "overlap_policy": body.get("overlap_policy", ScheduleOverlapPolicy.FORBID),
    }
    if existing.status is TaskScheduleStatus.DELETED or any(
        getattr(existing, key) != value for key, value in expected.items()
    ):
        return ApiResponse(409, {"status": "schedule_create_conflict"})
    return ApiResponse(200, schedule_body(existing))
