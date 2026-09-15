"""Bounded, replay-safe materialization of durable Schedule Firings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_schedule_authority import ScheduleAuthorityBinding
from agent_core.domain.task_schedules import ScheduleFiringStatus, TaskScheduleFiring
from agent_core.ports.task_schedule_materializer import (
    ScheduleAuthorityRevalidatorPort,
    ScheduledTaskAdmissionPort,
)
from agent_core.ports.task_schedules import (
    TaskScheduleFiringStorePort,
    TaskScheduleStorePort,
)


class ScheduleAuthorityRejected(ValueError):
    """Stable, non-secret reason that blocks one Firing permanently."""

    def __init__(self, code: str) -> None:
        normalized = code.strip().lower()
        if not normalized or len(normalized) > 128:
            raise ValueError("authority rejection code must be non-blank and bounded")
        super().__init__(normalized)
        self.code = normalized


@dataclass(frozen=True)
class ScheduleMaterializationBatch:
    claimed: int
    dispatched: int
    failed: int
    retrying: int


@dataclass(frozen=True)
class TaskScheduleMaterializer:
    schedules: TaskScheduleStorePort
    firings: TaskScheduleFiringStorePort
    authority: ScheduleAuthorityRevalidatorPort
    admission: ScheduledTaskAdmissionPort
    claimant: str
    batch_size: int = 20
    claim_ttl_seconds: int = 60
    max_attempts: int = 3
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def run_once(self) -> ScheduleMaterializationBatch:
        claimed = self.firings.claim_due(
            claimant=self.claimant,
            limit=self.batch_size,
            claim_ttl_seconds=self.claim_ttl_seconds,
        )
        dispatched = failed = retrying = 0
        for firing in claimed:
            outcome = self._materialize(firing)
            dispatched += outcome == "dispatched"
            failed += outcome == "failed"
            retrying += outcome == "retrying"
        return ScheduleMaterializationBatch(len(claimed), dispatched, failed, retrying)

    def _materialize(self, firing: TaskScheduleFiring) -> str:
        try:
            binding = self._current_authority(firing)
            execution_authority = self.authority.revalidate(binding, firing)
            task_id = self.admission.admit(
                firing.schedule_snapshot.task_template,
                binding=binding,
                firing=firing,
                execution_authority=execution_authority,
                idempotency_key=firing.idempotency_key,
            )
        except ScheduleAuthorityRejected as exc:
            self._fail(firing, f"authority_{exc.code}")
            return "failed"
        except Exception:
            if firing.attempt >= self.max_attempts:
                self._fail(firing, "materialization_attempts_exhausted")
                return "failed"
            return "retrying"
        self._dispatch(firing, task_id)
        return "dispatched"

    def _current_authority(self, firing: TaskScheduleFiring) -> ScheduleAuthorityBinding:
        snapshot = firing.schedule_snapshot
        binding = self.schedules.get_authority(snapshot.schedule_id, owner=snapshot.owner)
        if binding is None:
            raise ScheduleAuthorityRejected("missing")
        if binding.binding_id != snapshot.authority_binding_id:
            raise ScheduleAuthorityRejected("drifted")
        if binding.revoked_at is not None:
            raise ScheduleAuthorityRejected("revoked")
        return binding

    def _dispatch(self, firing: TaskScheduleFiring, task_id: TaskId) -> None:
        dispatched = firing.transition(
            ScheduleFiringStatus.DISPATCHED,
            at=self.now(),
            task_id=task_id,
        )
        self.firings.settle_firing(
            dispatched,
            expected_status=ScheduleFiringStatus.MATERIALIZING,
            expected_claim_expiry=firing.claim_expires_at,
        )

    def _fail(self, firing: TaskScheduleFiring, code: str) -> None:
        failed = firing.transition(
            ScheduleFiringStatus.FAILED,
            at=self.now(),
            failure_code=code,
        )
        self.firings.settle_firing(
            failed,
            expected_status=ScheduleFiringStatus.MATERIALIZING,
            expected_claim_expiry=firing.claim_expires_at,
        )
