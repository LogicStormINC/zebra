from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import pytest
from agent_core.application import next_fire_at, schedule_timezone
from agent_core.domain import TaskScheduleStatus as PublicTaskScheduleStatus
from agent_core.domain.identifiers import (
    TaskId,
    TaskScheduleFiringId,
    TaskScheduleId,
    task_schedule_firing_id,
)
from agent_core.domain.task_schedule_authority import (
    ScheduleAuthorityBinding,
    ScheduledTaskTemplate,
    ScheduleOwner,
)
from agent_core.domain.task_schedules import (
    DailyScheduleTrigger,
    IntervalScheduleTrigger,
    OnceScheduleTrigger,
    ScheduleFiringStatus,
    TaskSchedule,
    TaskScheduleFiring,
    TaskScheduleStatus,
    WeeklyScheduleTrigger,
)
from pydantic import ValidationError


def owner() -> ScheduleOwner:
    return ScheduleOwner(
        deployment_namespace=" trench ",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        principal_id="user-1",
        host_app_id="trench-toc",
    )


def schedule(**overrides: object) -> TaskSchedule:
    now = datetime(2026, 9, 15, 1, 0, tzinfo=UTC)
    values: dict[str, object] = {
        "schedule_id": TaskScheduleId(uuid4()),
        "owner": owner(),
        "title": " Daily research ",
        "timezone": "Asia/Shanghai",
        "trigger": DailyScheduleTrigger(local_time=time(9, 0)),
        "task_template": ScheduledTaskTemplate(payload={"prompt": "Summarize my sources"}),
        "authority_binding_id": uuid4(),
        "schedule_version": 1,
        "next_fire_at": datetime(2026, 9, 16, 1, 0, tzinfo=UTC),
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return TaskSchedule(**values)


def firing(**overrides: object) -> TaskScheduleFiring:
    now = datetime(2026, 9, 15, 1, 0, tzinfo=UTC)
    values: dict[str, object] = {
        "fire_id": TaskScheduleFiringId(uuid4()),
        "schedule_id": TaskScheduleId(uuid4()),
        "schedule_version": 1,
        "scheduled_for": now,
        "created_at": now,
    }
    values.update(overrides)
    return TaskScheduleFiring(**values)


def test_owner_and_schedule_normalize_identity_and_timestamps() -> None:
    item = schedule(
        next_fire_at=datetime.fromisoformat("2026-09-16T09:00:00+08:00"),
    )

    assert item.owner.deployment_namespace == "trench"
    assert item.title == "Daily research"
    assert item.next_fire_at == datetime(2026, 9, 16, 1, 0, tzinfo=UTC)
    assert PublicTaskScheduleStatus.ACTIVE is TaskScheduleStatus.ACTIVE


def test_schedule_rejects_invalid_timezone_and_contradictory_state() -> None:
    with pytest.raises(ValidationError, match="IANA timezone"):
        schedule(timezone="Mars/Olympus")
    with pytest.raises(ValidationError, match="active schedules require"):
        schedule(next_fire_at=None)
    with pytest.raises(ValidationError, match="terminal schedules"):
        schedule(status=TaskScheduleStatus.DELETED)


def test_schedule_lifecycle_is_versioned_and_delete_clears_due_time() -> None:
    active = schedule()
    paused = active.pause(at=datetime(2026, 9, 15, 2, 0, tzinfo=UTC))
    resumed = paused.resume(
        next_fire_at=datetime(2026, 9, 17, 1, 0, tzinfo=UTC),
        at=datetime(2026, 9, 15, 3, 0, tzinfo=UTC),
    )
    deleted = resumed.delete(at=datetime(2026, 9, 15, 4, 0, tzinfo=UTC))

    assert paused.status is TaskScheduleStatus.PAUSED
    assert resumed.schedule_version == 3
    assert deleted.schedule_version == 4
    assert deleted.next_fire_at is None
    with pytest.raises(ValueError, match="deleted again"):
        deleted.delete(at=datetime(2026, 9, 15, 5, 0, tzinfo=UTC))


def test_once_schedule_completes_without_masquerading_as_paused() -> None:
    fire_at = datetime(2026, 9, 16, 1, 0, tzinfo=UTC)
    once = schedule(
        trigger=OnceScheduleTrigger(fire_at=fire_at),
        next_fire_at=fire_at,
    )

    completed = once.complete(at=fire_at + timedelta(seconds=1), last_fire_at=fire_at)

    assert completed.status is TaskScheduleStatus.COMPLETED
    assert completed.next_fire_at is None
    assert completed.last_fire_at == fire_at
    with pytest.raises(ValueError, match="only once schedules"):
        schedule().complete(at=fire_at + timedelta(seconds=1), last_fire_at=fire_at)


@pytest.mark.parametrize("key", ["api_key", "auth-token", "CookieJar", "password"])
def test_task_template_never_persists_credential_like_fields(key: str) -> None:
    with pytest.raises(ValidationError, match="credential-like"):
        ScheduledTaskTemplate(payload={"prompt": "hello", "config": {key: "private"}})


def test_task_template_is_bounded_json_and_materializer_controls_execution() -> None:
    raw = {"prompt": "hello", "skill_components": ["better-writing@1"]}
    template = ScheduledTaskTemplate(
        payload=raw
    )

    assert len(template.template_digest) == 64
    raw["prompt"] = "mutated"
    decoded = template.payload
    decoded["prompt"] = "also mutated"
    assert template.payload["prompt"] == "hello"
    with pytest.raises(ValidationError, match="controlled by the materializer"):
        ScheduledTaskTemplate(payload={"prompt": "hello", "execute": True})
    with pytest.raises(ValidationError, match="JSON-compatible"):
        ScheduledTaskTemplate(payload={"prompt": "hello", "bad": object()})


def test_authority_binding_contains_digests_and_no_credentials() -> None:
    item = ScheduleAuthorityBinding(
        binding_id=uuid4(),
        schedule_id=TaskScheduleId(uuid4()),
        owner=owner(),
        host_capability_digest="A" * 64,
        agent_definition_digest="b" * 64,
        policy_digest="c" * 64,
        extension_snapshot_digest="d" * 64,
        binding_revision=1,
        bound_at=datetime(2026, 9, 15, 1, 0, tzinfo=UTC),
    )

    assert item.host_capability_digest == "a" * 64
    assert "token" not in ScheduleAuthorityBinding.model_fields
    assert "credential" not in ScheduleAuthorityBinding.model_fields
    revoked = item.revoke(at=datetime(2026, 9, 15, 2, 0, tzinfo=UTC))
    assert revoked.binding_revision == 2
    assert revoked.revoked_at == datetime(2026, 9, 15, 2, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="already revoked"):
        revoked.revoke(at=datetime(2026, 9, 15, 3, 0, tzinfo=UTC))


def test_once_and_interval_occurrences_are_strictly_after_boundary() -> None:
    at = datetime(2026, 9, 15, 1, 0, tzinfo=UTC)
    once = OnceScheduleTrigger(fire_at=at)
    interval = IntervalScheduleTrigger(anchor_at=at, every_seconds=3600)

    assert next_fire_at(once, timezone_name="UTC", after=at - timedelta(seconds=1)) == at
    assert next_fire_at(once, timezone_name="UTC", after=at) is None
    assert next_fire_at(interval, timezone_name="UTC", after=at) == at + timedelta(hours=1)
    assert next_fire_at(
        interval,
        timezone_name="UTC",
        after=at + timedelta(hours=2, minutes=30),
    ) == at + timedelta(hours=3)


def test_daily_and_weekly_use_user_wall_clock() -> None:
    daily = DailyScheduleTrigger(local_time=time(9, 0))
    weekly = WeeklyScheduleTrigger(local_time=time(10, 30), weekdays=(0, 4))

    assert next_fire_at(
        daily,
        timezone_name="Asia/Shanghai",
        after=datetime(2026, 9, 15, 0, 30, tzinfo=UTC),
    ) == datetime(2026, 9, 15, 1, 0, tzinfo=UTC)
    assert next_fire_at(
        weekly,
        timezone_name="Asia/Shanghai",
        after=datetime(2026, 9, 14, 3, 0, tzinfo=UTC),
    ) == datetime(2026, 9, 18, 2, 30, tzinfo=UTC)


def test_dst_gap_advances_to_first_valid_wall_time() -> None:
    trigger = DailyScheduleTrigger(local_time=time(2, 30))

    assert next_fire_at(
        trigger,
        timezone_name="America/New_York",
        after=datetime(2026, 3, 8, 5, 0, tzinfo=UTC),
    ) == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)


def test_dst_fold_fires_only_at_the_earlier_instant() -> None:
    trigger = DailyScheduleTrigger(local_time=time(1, 30))
    first = next_fire_at(
        trigger,
        timezone_name="America/New_York",
        after=datetime(2026, 11, 1, 4, 0, tzinfo=UTC),
    )

    assert first == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert next_fire_at(
        trigger,
        timezone_name="America/New_York",
        after=first,
    ) == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)


def test_invalid_timezone_and_naive_boundary_fail_closed() -> None:
    trigger = DailyScheduleTrigger(local_time=time(9, 0))

    with pytest.raises(ValueError, match="IANA timezone"):
        schedule_timezone("Mars/Olympus")
    with pytest.raises(ValueError, match="timezone-aware"):
        next_fire_at(trigger, timezone_name="UTC", after=datetime(2026, 9, 15, 1, 0))


def test_firing_requires_consistent_task_claim_and_terminal_evidence() -> None:
    now = datetime(2026, 9, 15, 1, 0, tzinfo=UTC)
    with pytest.raises(ValidationError, match="claim owner and expiry"):
        firing(claimed_by="scheduler-1")
    with pytest.raises(ValidationError, match="require task_id"):
        firing(status=ScheduleFiringStatus.DISPATCHED)
    with pytest.raises(ValidationError, match="terminal firings require"):
        firing(status=ScheduleFiringStatus.SKIPPED, failure_code="overlap")
    with pytest.raises(ValidationError, match="require failure_code"):
        firing(
            status=ScheduleFiringStatus.FAILED,
            completed_at=now + timedelta(seconds=1),
        )
    with pytest.raises(ValidationError, match="only valid"):
        firing(failure_code="unexpected")

    claimed = firing(claimed_by="scheduler-1", claim_expires_at=now + timedelta(seconds=30))
    assert claimed.claimed_by == "scheduler-1"


def test_firing_transition_is_monotonic_and_preserves_one_task() -> None:
    task_id = TaskId(uuid4())
    dispatched = firing().transition(
        ScheduleFiringStatus.DISPATCHED,
        at=datetime(2026, 9, 15, 1, 1, tzinfo=UTC),
        task_id=task_id,
    )
    completed = dispatched.transition(
        ScheduleFiringStatus.COMPLETED,
        at=datetime(2026, 9, 15, 1, 2, tzinfo=UTC),
    )

    assert completed.task_id == task_id
    assert completed.completed_at == datetime(2026, 9, 15, 1, 2, tzinfo=UTC)
    assert completed.idempotency_key.startswith("schedule-fire:")
    with pytest.raises(ValueError, match="invalid schedule firing transition"):
        completed.transition(
            ScheduleFiringStatus.DISPATCHED,
            at=datetime(2026, 9, 15, 1, 3, tzinfo=UTC),
        )


def test_firing_identity_is_deterministic_across_timezone_representations() -> None:
    schedule_id = TaskScheduleId(uuid4())
    utc = datetime(2026, 9, 15, 1, 0, tzinfo=UTC)
    shanghai = datetime.fromisoformat("2026-09-15T09:00:00+08:00")

    assert task_schedule_firing_id(schedule_id, utc) == task_schedule_firing_id(
        schedule_id,
        shanghai,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        task_schedule_firing_id(schedule_id, datetime(2026, 9, 15, 1, 0))


def test_transition_revalidates_generated_firing_evidence() -> None:
    with pytest.raises(ValidationError, match="require task_id"):
        firing().transition(
            ScheduleFiringStatus.DISPATCHED,
            at=datetime(2026, 9, 15, 1, 1, tzinfo=UTC),
        )
