"""Storage ports for user-owned Task schedules and immutable firings."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from agent_core.domain.identifiers import TaskScheduleFiringId, TaskScheduleId
from agent_core.domain.task_schedule_authority import ScheduleAuthorityBinding, ScheduleOwner
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

    def get(
        self,
        schedule_id: TaskScheduleId,
        *,
        owner: ScheduleOwner,
    ) -> TaskSchedule | None: ...

    def get_authority(
        self,
        schedule_id: TaskScheduleId,
        *,
        owner: ScheduleOwner,
    ) -> ScheduleAuthorityBinding | None: ...

    def list_for_owner(
        self,
        owner: ScheduleOwner,
        *,
        limit: int,
    ) -> tuple[TaskSchedule, ...]: ...

    def revoke_authority(
        self,
        authority: ScheduleAuthorityBinding,
        *,
        expected_revision: int,
    ) -> ScheduleAuthorityBinding: ...

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
        claimant: str,
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
