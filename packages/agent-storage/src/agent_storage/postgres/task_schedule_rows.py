"""Integrity checks for PostgreSQL Task Schedule rows."""

from __future__ import annotations

from typing import Any

from agent_core.domain.task_schedule_authority import (
    ScheduleAuthorityBinding,
    ScheduleOwner,
)
from agent_core.domain.task_schedules import TaskSchedule, TaskScheduleFiring
from pydantic import ValidationError


class TaskScheduleStorageIntegrityError(RuntimeError):
    pass


def owner_values(owner: ScheduleOwner) -> tuple[str, str, str, str]:
    return (owner.tenant_id, owner.workspace_id, owner.principal_id, owner.host_app_id)


def validate_owner(owner: ScheduleOwner, deployment_namespace: str) -> ScheduleOwner:
    if not isinstance(owner, ScheduleOwner):
        raise TypeError("owner must be a ScheduleOwner")
    trusted = ScheduleOwner.model_validate(owner.model_dump())
    if trusted.deployment_namespace != deployment_namespace:
        raise ValueError("schedule owner belongs to another deployment namespace")
    return trusted


def decode_schedule(row: dict[str, Any]) -> TaskSchedule:
    try:
        schedule = TaskSchedule.model_validate(row["payload"])
    except (KeyError, TypeError, ValidationError) as exc:
        raise TaskScheduleStorageIntegrityError("invalid stored Task Schedule") from exc
    indexed = (
        row["deployment_namespace"],
        row["tenant_id"],
        row["workspace_id"],
        row["principal_id"],
        row["host_app_id"],
        row["schedule_id"],
        row["title"],
        row["status"],
        row["schedule_version"],
        row["next_fire_at"],
        row["last_fire_at"],
        row["authority_binding_id"],
        row["created_at"],
        row["updated_at"],
    )
    expected = (
        schedule.owner.deployment_namespace,
        *owner_values(schedule.owner),
        schedule.schedule_id,
        schedule.title,
        schedule.status,
        schedule.schedule_version,
        schedule.next_fire_at,
        schedule.last_fire_at,
        schedule.authority_binding_id,
        schedule.created_at,
        schedule.updated_at,
    )
    if indexed != expected:
        raise TaskScheduleStorageIntegrityError("Task Schedule payload disagrees with indexes")
    return schedule


def decode_authority(row: dict[str, Any]) -> ScheduleAuthorityBinding:
    try:
        authority = ScheduleAuthorityBinding.model_validate(row["payload"])
    except (KeyError, TypeError, ValidationError) as exc:
        raise TaskScheduleStorageIntegrityError("invalid stored Schedule authority") from exc
    indexed = (
        row["deployment_namespace"],
        row["tenant_id"],
        row["workspace_id"],
        row["principal_id"],
        row["host_app_id"],
        row["binding_id"],
        row["schedule_id"],
        row["binding_revision"],
        row["revoked_at"],
    )
    expected = (
        authority.owner.deployment_namespace,
        *owner_values(authority.owner),
        authority.binding_id,
        authority.schedule_id,
        authority.binding_revision,
        authority.revoked_at,
    )
    if indexed != expected:
        raise TaskScheduleStorageIntegrityError("Schedule authority payload disagrees with indexes")
    return authority


def decode_firing(row: dict[str, Any]) -> TaskScheduleFiring:
    try:
        return TaskScheduleFiring.model_validate(
            {key: row[key] for key in TaskScheduleFiring.model_fields}
        )
    except (KeyError, TypeError, ValidationError) as exc:
        raise TaskScheduleStorageIntegrityError("invalid stored Schedule Firing") from exc
