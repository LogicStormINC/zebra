"""Storage-neutral contracts for user-owned Cloud Agent schedules."""

from __future__ import annotations

from datetime import UTC, datetime, time
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.identifiers import TaskId, TaskScheduleFiringId, TaskScheduleId
from agent_core.domain.task_schedule_authority import (
    ScheduledTaskTemplate,
    ScheduleOwner,
)


class TaskScheduleStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    DELETED = "deleted"


class ScheduleMisfirePolicy(StrEnum):
    COALESCE_ONE = "coalesce_one"
    SKIP = "skip"


class ScheduleOverlapPolicy(StrEnum):
    FORBID = "forbid"
    ALLOW = "allow"


class ScheduleFiringStatus(StrEnum):
    MATERIALIZING = "materializing"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


SCHEDULE_FIRING_TERMINAL_STATUSES = frozenset(
    {
        ScheduleFiringStatus.COMPLETED,
        ScheduleFiringStatus.FAILED,
        ScheduleFiringStatus.SKIPPED,
    }
)


def _utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _normalized_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


class OnceScheduleTrigger(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["once"] = "once"
    fire_at: datetime

    @field_validator("fire_at")
    @classmethod
    def normalize_fire_at(cls, value: datetime) -> datetime:
        return _utc(value, field_name="fire_at")


class IntervalScheduleTrigger(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["interval"] = "interval"
    anchor_at: datetime
    every_seconds: int = Field(ge=60, le=31_536_000)

    @field_validator("anchor_at")
    @classmethod
    def normalize_anchor(cls, value: datetime) -> datetime:
        return _utc(value, field_name="anchor_at")


class _CalendarScheduleTrigger(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    local_time: time

    @field_validator("local_time")
    @classmethod
    def minute_precision(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("local_time must not carry a timezone")
        if value.second or value.microsecond:
            raise ValueError("local_time supports minute precision")
        return value


class DailyScheduleTrigger(_CalendarScheduleTrigger):
    kind: Literal["daily"] = "daily"


class WeeklyScheduleTrigger(_CalendarScheduleTrigger):
    kind: Literal["weekly"] = "weekly"
    weekdays: tuple[int, ...] = Field(min_length=1, max_length=7)

    @field_validator("weekdays")
    @classmethod
    def normalize_weekdays(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("weekdays must contain integers from 0 to 6")
        normalized = tuple(sorted(set(value)))
        if len(normalized) != len(value):
            raise ValueError("weekdays must not contain duplicates")
        return normalized


ScheduleTrigger = Annotated[
    OnceScheduleTrigger | IntervalScheduleTrigger | DailyScheduleTrigger | WeeklyScheduleTrigger,
    Field(discriminator="kind"),
]


class TaskSchedule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schedule_id: TaskScheduleId
    owner: ScheduleOwner
    title: str = Field(max_length=256)
    timezone: str = Field(max_length=128)
    trigger: ScheduleTrigger
    task_template: ScheduledTaskTemplate
    authority_binding_id: UUID
    status: TaskScheduleStatus = TaskScheduleStatus.ACTIVE
    schedule_version: int = Field(ge=1)
    next_fire_at: datetime | None
    last_fire_at: datetime | None = None
    misfire_policy: ScheduleMisfirePolicy = ScheduleMisfirePolicy.COALESCE_ONE
    misfire_grace_seconds: int = Field(default=3_600, ge=0, le=604_800)
    overlap_policy: ScheduleOverlapPolicy = ScheduleOverlapPolicy.FORBID
    created_at: datetime
    updated_at: datetime

    @field_validator("title", "timezone")
    @classmethod
    def normalize_schedule_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "schedule field")
        normalized = _normalized_text(value, field_name=field_name)
        if field_name == "timezone":
            try:
                ZoneInfo(normalized)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError("timezone must be a valid IANA timezone") from exc
        return normalized

    @field_validator("next_fire_at", "last_fire_at", "created_at", "updated_at")
    @classmethod
    def normalize_schedule_time(cls, value: datetime | None, info: object) -> datetime | None:
        if value is None:
            return None
        field_name = getattr(info, "field_name", "schedule timestamp")
        return _utc(value, field_name=field_name)

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.status is TaskScheduleStatus.ACTIVE and self.next_fire_at is None:
            raise ValueError("active schedules require next_fire_at")
        if self.status in {
            TaskScheduleStatus.COMPLETED,
            TaskScheduleStatus.DELETED,
        } and self.next_fire_at is not None:
            raise ValueError("terminal schedules must not retain next_fire_at")
        return self

    def pause(self, *, at: datetime) -> TaskSchedule:
        if self.status is not TaskScheduleStatus.ACTIVE:
            raise ValueError("only active schedules can be paused")
        moment = _utc(at, field_name="at")
        if moment < self.updated_at:
            raise ValueError("schedule update time cannot move backwards")
        return TaskSchedule.model_validate(
            {
                **self.model_dump(),
                "status": TaskScheduleStatus.PAUSED,
                "schedule_version": self.schedule_version + 1,
                "updated_at": moment,
            }
        )

    def resume(self, *, next_fire_at: datetime, at: datetime) -> TaskSchedule:
        if self.status is not TaskScheduleStatus.PAUSED:
            raise ValueError("only paused schedules can be resumed")
        moment = _utc(at, field_name="at")
        if moment < self.updated_at:
            raise ValueError("schedule update time cannot move backwards")
        return TaskSchedule.model_validate(
            {
                **self.model_dump(),
                "status": TaskScheduleStatus.ACTIVE,
                "next_fire_at": _utc(next_fire_at, field_name="next_fire_at"),
                "schedule_version": self.schedule_version + 1,
                "updated_at": moment,
            }
        )

    def delete(self, *, at: datetime) -> TaskSchedule:
        if self.status is TaskScheduleStatus.DELETED:
            raise ValueError("deleted schedules cannot be deleted again")
        moment = _utc(at, field_name="at")
        if moment < self.updated_at:
            raise ValueError("schedule update time cannot move backwards")
        return TaskSchedule.model_validate(
            {
                **self.model_dump(),
                "status": TaskScheduleStatus.DELETED,
                "next_fire_at": None,
                "schedule_version": self.schedule_version + 1,
                "updated_at": moment,
            }
        )

    def complete(self, *, at: datetime, last_fire_at: datetime) -> TaskSchedule:
        if self.status is not TaskScheduleStatus.ACTIVE:
            raise ValueError("only active schedules can complete")
        if not isinstance(self.trigger, OnceScheduleTrigger):
            raise ValueError("only once schedules can complete")
        moment = _utc(at, field_name="at")
        fired_at = _utc(last_fire_at, field_name="last_fire_at")
        if moment < self.updated_at or moment < fired_at:
            raise ValueError("schedule completion time cannot move backwards")
        return TaskSchedule.model_validate(
            {
                **self.model_dump(),
                "status": TaskScheduleStatus.COMPLETED,
                "next_fire_at": None,
                "last_fire_at": fired_at,
                "schedule_version": self.schedule_version + 1,
                "updated_at": moment,
            }
        )


class TaskScheduleFiring(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fire_id: TaskScheduleFiringId
    schedule_id: TaskScheduleId
    schedule_version: int = Field(ge=1)
    scheduled_for: datetime
    status: ScheduleFiringStatus = ScheduleFiringStatus.MATERIALIZING
    task_id: TaskId | None = None
    attempt: int = Field(default=0, ge=0)
    failure_code: str | None = Field(default=None, max_length=128)
    claimed_by: str | None = Field(default=None, max_length=256)
    claim_expires_at: datetime | None = None
    created_at: datetime
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("failure_code", "claimed_by")
    @classmethod
    def normalize_optional_text(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return None
        field_name = getattr(info, "field_name", "firing field")
        return _normalized_text(value, field_name=field_name)

    @field_validator(
        "scheduled_for",
        "claim_expires_at",
        "created_at",
        "dispatched_at",
        "completed_at",
    )
    @classmethod
    def normalize_firing_time(cls, value: datetime | None, info: object) -> datetime | None:
        if value is None:
            return None
        field_name = getattr(info, "field_name", "firing timestamp")
        return _utc(value, field_name=field_name)

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if (self.claimed_by is None) != (self.claim_expires_at is None):
            raise ValueError("claim owner and expiry must be present together")
        if self.claim_expires_at is not None and self.claim_expires_at <= self.created_at:
            raise ValueError("claim expiry must be after creation")
        if self.status in {
            ScheduleFiringStatus.DISPATCHED,
            ScheduleFiringStatus.COMPLETED,
        } and self.task_id is None:
            raise ValueError("dispatched or completed firings require task_id")
        if self.dispatched_at is not None and self.task_id is None:
            raise ValueError("dispatched_at requires task_id")
        if self.dispatched_at is not None and self.dispatched_at < self.created_at:
            raise ValueError("dispatched_at must not precede created_at")
        if self.status in SCHEDULE_FIRING_TERMINAL_STATUSES and self.completed_at is None:
            raise ValueError("terminal firings require completed_at")
        if self.status not in SCHEDULE_FIRING_TERMINAL_STATUSES and self.completed_at is not None:
            raise ValueError("non-terminal firings must not carry completed_at")
        if self.failure_code is not None and self.status not in {
            ScheduleFiringStatus.FAILED,
            ScheduleFiringStatus.SKIPPED,
        }:
            raise ValueError("failure_code is only valid for failed or skipped firings")
        if self.status in {
            ScheduleFiringStatus.FAILED,
            ScheduleFiringStatus.SKIPPED,
        } and self.failure_code is None:
            raise ValueError("failed or skipped firings require failure_code")
        if self.completed_at is not None:
            lower_bound = self.dispatched_at or self.created_at
            if self.completed_at < lower_bound:
                raise ValueError("completed_at must not precede prior firing evidence")
        return self

    @property
    def idempotency_key(self) -> str:
        return f"schedule-fire:{self.schedule_id}:{self.scheduled_for.isoformat()}"

    def transition(
        self,
        status: ScheduleFiringStatus,
        *,
        at: datetime,
        task_id: TaskId | None = None,
        failure_code: str | None = None,
    ) -> TaskScheduleFiring:
        allowed = {
            ScheduleFiringStatus.MATERIALIZING: {
                ScheduleFiringStatus.DISPATCHED,
                ScheduleFiringStatus.FAILED,
                ScheduleFiringStatus.SKIPPED,
            },
            ScheduleFiringStatus.DISPATCHED: {
                ScheduleFiringStatus.COMPLETED,
                ScheduleFiringStatus.FAILED,
            },
            ScheduleFiringStatus.COMPLETED: set(),
            ScheduleFiringStatus.FAILED: set(),
            ScheduleFiringStatus.SKIPPED: set(),
        }
        if status not in allowed[self.status]:
            raise ValueError(f"invalid schedule firing transition: {self.status} -> {status}")
        moment = _utc(at, field_name="at")
        resolved_task_id = task_id or self.task_id
        updates: dict[str, object] = {
            "status": status,
            "task_id": resolved_task_id,
            "failure_code": failure_code,
        }
        if status is ScheduleFiringStatus.DISPATCHED:
            updates["dispatched_at"] = moment
        if status in SCHEDULE_FIRING_TERMINAL_STATUSES:
            updates["completed_at"] = moment
        return TaskScheduleFiring.model_validate({**self.model_dump(), **updates})
