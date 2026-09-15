from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

from agent_core.application import ScheduleAuthorityRejected, TaskScheduleMaterializer
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskId, TaskScheduleId
from agent_core.domain.task_bindings import host_context_digest
from agent_core.domain.task_schedule_authority import (
    ScheduleAuthorityBinding,
    ScheduledTaskTemplate,
    ScheduleExecutionAuthority,
    ScheduleOwner,
)
from agent_core.domain.task_schedules import (
    DailyScheduleTrigger,
    ScheduleFiringStatus,
    TaskSchedule,
    TaskScheduleFiring,
)

NOW = datetime(2026, 9, 15, 4, 0, tzinfo=UTC)


def context() -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id="login-grant",
        host_app_id="trench",
        namespace_id="tenant-1",
        workspace_ref="workspace-1",
        resource_refs=({"type": "principal", "id": "user-1"},),
        scopes=("agent.run", "schedule.manage"),
        limits={
            "max_runtime_seconds": 1800,
            "max_model_tokens": 1_000_000,
            "max_artifact_bytes": 64_000_000,
        },
        origin="https://trench.example",
        policy_version="policy-v1",
    )


def schedule_and_authority() -> tuple[TaskSchedule, ScheduleAuthorityBinding]:
    schedule_id = TaskScheduleId(uuid4())
    binding_id = uuid4()
    owner = ScheduleOwner(
        deployment_namespace="cloud",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        principal_id="user-1",
        host_app_id="trench",
    )
    item = TaskSchedule(
        schedule_id=schedule_id,
        owner=owner,
        title="Daily report",
        timezone="Asia/Shanghai",
        trigger=DailyScheduleTrigger(local_time=time(9)),
        task_template=ScheduledTaskTemplate(payload={"prompt": "Summarize my sources"}),
        authority_binding_id=binding_id,
        schedule_version=1,
        next_fire_at=NOW,
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
    )
    host = context()
    authority = ScheduleAuthorityBinding(
        binding_id=binding_id,
        schedule_id=schedule_id,
        owner=owner,
        host_context=host,
        host_capability_digest=host_context_digest(host),
        agent_definition_digest="a" * 64,
        policy_digest="b" * 64,
        extension_snapshot_digest="c" * 64,
        binding_revision=1,
        bound_at=NOW - timedelta(days=1),
    )
    return item, authority


def firing(item: TaskSchedule, *, attempt: int = 1) -> TaskScheduleFiring:
    return TaskScheduleFiring(
        fire_id=uuid4(),
        schedule_id=item.schedule_id,
        schedule_version=item.schedule_version,
        schedule_snapshot=item,
        scheduled_for=NOW,
        attempt=attempt,
        claimed_by="scheduler-1",
        claim_expires_at=NOW + timedelta(minutes=1),
        created_at=NOW,
    )


class ScheduleStore:
    def __init__(self, authority: ScheduleAuthorityBinding | None) -> None:
        self.authority = authority

    def get_authority(
        self, schedule_id: object, *, owner: object
    ) -> ScheduleAuthorityBinding | None:
        return self.authority


class FiringStore:
    def __init__(self, item: TaskScheduleFiring) -> None:
        self.item = item
        self.settled: list[TaskScheduleFiring] = []

    def claim_due(self, **_: object) -> tuple[TaskScheduleFiring, ...]:
        return (self.item,)

    def settle_firing(self, item: TaskScheduleFiring, **_: object) -> TaskScheduleFiring:
        self.settled.append(item)
        return item


class Authority:
    def __init__(self, rejection: str | None = None) -> None:
        self.rejection = rejection

    def revalidate(
        self, binding: ScheduleAuthorityBinding, firing: TaskScheduleFiring
    ) -> ScheduleExecutionAuthority:
        if self.rejection is not None:
            raise ScheduleAuthorityRejected(self.rejection)
        return ScheduleExecutionAuthority(
            host_context=binding.host_context,
            authority_issuer="https://broker.example",
            grant_id=binding.host_context.grant_id,
            subject_ref=binding.owner.principal_id,
            algorithm="RS256",
        )


class Admission:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.idempotency_keys: list[str] = []
        self.task_id = TaskId(uuid4())

    def admit(self, template: object, **kwargs: object) -> TaskId:
        self.idempotency_keys.append(str(kwargs["idempotency_key"]))
        if self.error is not None:
            raise self.error
        return self.task_id


def materializer(
    item: TaskScheduleFiring,
    binding: ScheduleAuthorityBinding | None,
    admission: Admission,
    *,
    authority: Authority | None = None,
) -> tuple[TaskScheduleMaterializer, FiringStore]:
    firings = FiringStore(item)
    service = TaskScheduleMaterializer(
        schedules=ScheduleStore(binding),  # type: ignore[arg-type]
        firings=firings,  # type: ignore[arg-type]
        authority=authority or Authority(),
        admission=admission,  # type: ignore[arg-type]
        claimant="scheduler-1",
        now=lambda: NOW + timedelta(seconds=1),
    )
    return service, firings


def test_materializer_dispatches_once_with_stable_firing_key() -> None:
    item, binding = schedule_and_authority()
    claimed = firing(item)
    admission = Admission()
    service, firings = materializer(claimed, binding, admission)

    result = service.run_once()

    assert result.dispatched == 1
    assert firings.settled[0].status is ScheduleFiringStatus.DISPATCHED
    assert firings.settled[0].task_id == admission.task_id
    assert admission.idempotency_keys == [claimed.idempotency_key]


def test_materializer_fails_closed_for_missing_drifted_or_rejected_authority() -> None:
    item, binding = schedule_and_authority()
    cases = (
        (None, None, "authority_missing"),
        (binding.model_copy(update={"binding_id": uuid4()}), None, "authority_drifted"),
        (binding, Authority("user_inactive"), "authority_user_inactive"),
    )
    for current, revalidator, expected in cases:
        service, firings = materializer(firing(item), current, Admission(), authority=revalidator)
        result = service.run_once()
        assert result.failed == 1
        assert firings.settled[0].failure_code == expected


def test_transient_failure_retries_then_terminalizes_at_bound() -> None:
    item, binding = schedule_and_authority()
    transient = Admission(error=RuntimeError("broker unavailable"))
    service, firings = materializer(firing(item, attempt=1), binding, transient)

    assert service.run_once().retrying == 1
    assert firings.settled == []

    exhausted, exhausted_store = materializer(firing(item, attempt=3), binding, transient)
    assert exhausted.run_once().failed == 1
    assert exhausted_store.settled[0].failure_code == "materialization_attempts_exhausted"
