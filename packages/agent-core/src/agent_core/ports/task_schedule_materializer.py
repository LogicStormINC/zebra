"""Ports crossing the Schedule authority and Task admission boundaries."""

from __future__ import annotations

from typing import Protocol

from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_schedule_authority import (
    ScheduleAuthorityBinding,
    ScheduledTaskTemplate,
    ScheduleExecutionAuthority,
)
from agent_core.domain.task_schedules import TaskScheduleFiring


class ScheduleAuthorityRevalidatorPort(Protocol):
    def revalidate(
        self,
        binding: ScheduleAuthorityBinding,
        firing: TaskScheduleFiring,
    ) -> ScheduleExecutionAuthority: ...


class ScheduledTaskAdmissionPort(Protocol):
    def admit(
        self,
        template: ScheduledTaskTemplate,
        *,
        binding: ScheduleAuthorityBinding,
        firing: TaskScheduleFiring,
        execution_authority: ScheduleExecutionAuthority,
        idempotency_key: str,
    ) -> TaskId: ...
