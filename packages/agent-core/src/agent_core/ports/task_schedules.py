"""Storage ports for user-owned Task schedules and immutable firings."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from agent_core.domain.identifiers import TaskScheduleFiringId, TaskScheduleId
from agent_core.domain.task_schedule_authority import ScheduleAuthorityBinding
from agent_core.domain.task_schedules import (
    ScheduleFiringStatus,
    TaskSchedule,
    TaskScheduleFiring,
)


class TaskScheduleConflictError(RuntimeError):
    pass


class TaskScheduleStorePort(Protocol):
    def create(
        self,
        schedule: TaskSchedule,
        authority: ScheduleAuthorityBinding,
    ) -> TaskSchedule: ...

    def get(self, schedule_id: TaskScheduleId) -> TaskSchedule | None: ...

    def get_authority(
        self,
        schedule_id: TaskScheduleId,
    ) -> ScheduleAuthorityBinding | None: ...

    def update(
        self,
        schedule: TaskSchedule,
        *,
        expected_version: int,
    ) -> TaskSchedule: ...


class TaskScheduleFiringStorePort(Protocol):
    def claim_due(
        self,
        *,
        owner: str,
        limit: int,
        claim_ttl_seconds: int,
    ) -> tuple[TaskScheduleFiring, ...]: ...

    def get_firing(
        self,
        fire_id: TaskScheduleFiringId,
    ) -> TaskScheduleFiring | None: ...

    def settle_firing(
        self,
        firing: TaskScheduleFiring,
        *,
        expected_status: ScheduleFiringStatus,
        expected_claim_expiry: datetime | None,
    ) -> TaskScheduleFiring: ...
