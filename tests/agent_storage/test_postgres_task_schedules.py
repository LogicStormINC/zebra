from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskId, TaskScheduleId
from agent_core.domain.task_bindings import host_context_digest
from agent_core.domain.task_schedule_authority import (
    ScheduleAuthorityBinding,
    ScheduledTaskTemplate,
    ScheduleOwner,
)
from agent_core.domain.task_schedules import (
    DailyScheduleTrigger,
    OnceScheduleTrigger,
    ScheduleFiringStatus,
    TaskSchedule,
    TaskScheduleStatus,
)
from agent_core.ports.task_schedules import TaskScheduleConflictError
from agent_storage import apply_postgres_migrations
from agent_storage.postgres.migrations import MIGRATIONS
from agent_storage.postgres.task_schedule_firings import PostgresTaskScheduleFiringStore
from agent_storage.postgres.task_schedules import PostgresTaskScheduleStore
from psycopg import sql
from psycopg.conninfo import make_conninfo
from pydantic import ValidationError


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    value = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not value:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return value


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"task_schedules_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def owner(*, principal: str = "user-1") -> ScheduleOwner:
    return ScheduleOwner(
        deployment_namespace="cloud",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        principal_id=principal,
        host_app_id="trench",
    )


def host_context(schedule_owner: ScheduleOwner) -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id="grant-1",
        host_app_id=schedule_owner.host_app_id,
        namespace_id=schedule_owner.tenant_id,
        workspace_ref=schedule_owner.workspace_id,
        resource_refs=({"type": "principal", "id": schedule_owner.principal_id},),
        scopes=("agent.run", "schedule.manage"),
        limits={
            "max_runtime_seconds": 1800,
            "max_model_tokens": 1_000_000,
            "max_artifact_bytes": 64_000_000,
        },
        origin="https://trench.example",
        policy_version="trench-read-v1",
    )


def schedule(
    *,
    schedule_id: TaskScheduleId | None = None,
    schedule_owner: ScheduleOwner | None = None,
    once: bool = False,
    next_fire_at: datetime | None = None,
    misfire_grace_seconds: int = 3_600,
) -> tuple[TaskSchedule, ScheduleAuthorityBinding]:
    now = datetime.now(UTC)
    due = next_fire_at or now + timedelta(hours=1)
    identity = schedule_id or TaskScheduleId(uuid4())
    trusted_owner = schedule_owner or owner()
    binding_id = uuid4()
    item = TaskSchedule(
        schedule_id=identity,
        owner=trusted_owner,
        title="Daily research",
        timezone="Asia/Shanghai",
        trigger=(
            OnceScheduleTrigger(fire_at=due)
            if once
            else DailyScheduleTrigger(local_time=time(9, 0))
        ),
        task_template=ScheduledTaskTemplate.model_validate(
            {"payload": {"prompt": "Summarize my sources"}}
        ),
        authority_binding_id=binding_id,
        schedule_version=1,
        next_fire_at=due,
        misfire_grace_seconds=misfire_grace_seconds,
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(days=1),
    )
    authority = ScheduleAuthorityBinding(
        binding_id=binding_id,
        schedule_id=identity,
        owner=trusted_owner,
        host_context=host_context(trusted_owner),
        host_capability_digest=host_context_digest(host_context(trusted_owner)),
        agent_definition_digest="b" * 64,
        policy_digest="c" * 64,
        extension_snapshot_digest="d" * 64,
        binding_revision=1,
        bound_at=now - timedelta(days=1),
    )
    return item, authority


def test_migration_is_forward_only_v58() -> None:
    migration = next(item for item in MIGRATIONS if item.name == "user_task_schedules")

    assert migration.version == 58
    assert not any("DROP TABLE" in statement.upper() for statement in migration.statements)


def test_owner_scoped_crud_authority_and_cas(dsn: str) -> None:
    store = PostgresTaskScheduleStore(dsn, deployment_namespace="cloud")
    item, authority = schedule()

    assert store.create(item, authority) == item
    assert store.get(item.schedule_id, owner=item.owner) == item
    assert store.get_authority(item.schedule_id, owner=item.owner) == authority
    assert store.list_for_owner(item.owner, limit=10) == (item,)
    assert store.get(item.schedule_id, owner=owner(principal="user-2")) is None
    assert store.list_for_owner(owner(principal="user-2"), limit=10) == ()

    revoked = authority.revoke(at=datetime.now(UTC))
    assert store.revoke_authority(revoked, expected_revision=1) == revoked
    with pytest.raises(TaskScheduleConflictError):
        store.revoke_authority(revoked, expected_revision=1)

    paused = item.pause(at=datetime.now(UTC))
    assert store.update(paused, expected_version=1) == paused
    with pytest.raises(TaskScheduleConflictError):
        store.update(paused.model_copy(update={"schedule_version": 2}), expected_version=1)
    with pytest.raises(TaskScheduleConflictError):
        store.create(item, authority)


def test_manual_firing_is_idempotent_and_owner_scoped(dsn: str) -> None:
    schedules = PostgresTaskScheduleStore(dsn, deployment_namespace="cloud")
    firings = PostgresTaskScheduleFiringStore(dsn, deployment_namespace="cloud")
    item, authority = schedule()
    schedules.create(item, authority)

    first = firings.create_manual(item, owner=item.owner, idempotency_key="run-now-1")
    replayed = firings.create_manual(item, owner=item.owner, idempotency_key="run-now-1")

    assert replayed == first
    assert firings.list_for_schedule(item.schedule_id, owner=item.owner, limit=10) == (first,)
    assert (
        firings.get_for_owner(
            first.fire_id,
            schedule_id=item.schedule_id,
            owner=item.owner,
        )
        == first
    )
    other = owner(principal="user-2")
    assert firings.list_for_schedule(item.schedule_id, owner=other, limit=10) == ()
    assert firings.get_for_owner(first.fire_id, schedule_id=item.schedule_id, owner=other) is None


def test_template_change_replaces_authority_atomically(dsn: str) -> None:
    store = PostgresTaskScheduleStore(dsn, deployment_namespace="cloud")
    item, authority = schedule()
    store.create(item, authority)
    moment = datetime.now(UTC)
    replacement = ScheduleAuthorityBinding(
        **{
            **authority.model_dump(),
            "binding_id": uuid4(),
            "binding_revision": 1,
            "bound_at": moment,
        }
    )
    changed = TaskSchedule.model_validate(
        {
            **item.model_dump(),
            "task_template": {"payload": {"prompt": "Updated report"}},
            "authority_binding_id": replacement.binding_id,
            "schedule_version": 2,
            "updated_at": moment,
        }
    )

    assert (
        store.replace_authority(
            changed,
            replacement,
            authority.revoke(at=moment),
            expected_version=1,
            expected_authority_revision=1,
        )
        == changed
    )
    assert store.get_authority(item.schedule_id, owner=item.owner) == replacement
    with store.connect() as connection:
        old = connection.execute(
            "SELECT revoked_at FROM schedule_authority_bindings WHERE binding_id = %s",
            (authority.binding_id,),
        ).fetchone()
    assert old is not None and old["revoked_at"] is not None


def test_due_claim_advances_schedule_and_settles_firing(dsn: str) -> None:
    schedules = PostgresTaskScheduleStore(dsn, deployment_namespace="cloud")
    firings = PostgresTaskScheduleFiringStore(dsn, deployment_namespace="cloud")
    due = datetime.now(UTC) - timedelta(seconds=5)
    item, authority = schedule(next_fire_at=due)
    schedules.create(item, authority)

    (claimed,) = firings.claim_due(claimant="scheduler-a", limit=10, claim_ttl_seconds=30)

    assert claimed.schedule_id == item.schedule_id
    assert claimed.schedule_snapshot == item
    assert claimed.scheduled_for == due
    assert claimed.status is ScheduleFiringStatus.MATERIALIZING
    assert claimed.attempt == 1
    advanced = schedules.get(item.schedule_id, owner=item.owner)
    assert advanced is not None
    assert advanced.last_fire_at == due
    assert advanced.next_fire_at is not None and advanced.next_fire_at > datetime.now(UTC)

    dispatched = claimed.transition(
        ScheduleFiringStatus.DISPATCHED,
        at=claimed.created_at + timedelta(seconds=1),
        task_id=TaskId(uuid4()),
    )
    assert (
        firings.settle_firing(
            dispatched,
            expected_status=ScheduleFiringStatus.MATERIALIZING,
            expected_claim_expiry=claimed.claim_expires_at,
        )
        == dispatched
    )
    completed = dispatched.transition(
        ScheduleFiringStatus.COMPLETED,
        at=claimed.created_at + timedelta(seconds=2),
    )
    assert (
        firings.settle_firing(
            completed,
            expected_status=ScheduleFiringStatus.DISPATCHED,
            expected_claim_expiry=claimed.claim_expires_at,
        )
        == completed
    )
    with pytest.raises(ValidationError, match="schedule_snapshot"):
        firings.settle_firing(
            completed.model_copy(update={"schedule_id": TaskScheduleId(uuid4())}),
            expected_status=ScheduleFiringStatus.COMPLETED,
            expected_claim_expiry=claimed.claim_expires_at,
        )


def test_once_misfire_is_recorded_and_schedule_completes(dsn: str) -> None:
    schedules = PostgresTaskScheduleStore(dsn, deployment_namespace="cloud")
    firings = PostgresTaskScheduleFiringStore(dsn, deployment_namespace="cloud")
    due = datetime.now(UTC) - timedelta(minutes=5)
    item, authority = schedule(
        once=True,
        next_fire_at=due,
        misfire_grace_seconds=1,
    )
    schedules.create(item, authority)

    assert firings.claim_due(claimant="scheduler-a", limit=10, claim_ttl_seconds=30) == ()
    completed = schedules.get(item.schedule_id, owner=item.owner)
    assert completed is not None
    assert completed.status is TaskScheduleStatus.COMPLETED
    with firings.connect() as connection:
        row = connection.execute(
            "SELECT fire_id FROM task_schedule_firings WHERE schedule_id = %s",
            (item.schedule_id,),
        ).fetchone()
    assert row is not None
    skipped = firings.get_firing(row["fire_id"])
    assert skipped is not None
    assert skipped.status is ScheduleFiringStatus.SKIPPED
    assert skipped.failure_code == "misfire_grace_expired"


def test_expired_materialization_claim_recovers_without_second_firing(dsn: str) -> None:
    schedules = PostgresTaskScheduleStore(dsn, deployment_namespace="cloud")
    first = PostgresTaskScheduleFiringStore(dsn, deployment_namespace="cloud")
    second = PostgresTaskScheduleFiringStore(dsn, deployment_namespace="cloud")
    item, authority = schedule(next_fire_at=datetime.now(UTC) - timedelta(seconds=2))
    schedules.create(item, authority)
    (claimed,) = first.claim_due(claimant="scheduler-a", limit=1, claim_ttl_seconds=30)
    with first.connect() as connection:
        connection.execute(
            "UPDATE task_schedule_firings SET created_at = created_at - interval '60 seconds', "
            "claim_expires_at = clock_timestamp() - interval '1 second' WHERE fire_id = %s",
            (claimed.fire_id,),
        )

    (recovered,) = second.claim_due(claimant="scheduler-b", limit=1, claim_ttl_seconds=30)

    assert recovered.fire_id == claimed.fire_id
    assert recovered.attempt == 2
    assert recovered.claimed_by == "scheduler-b"
    with second.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM task_schedule_firings").fetchone() == {
            "n": 1
        }


def test_forbidden_overlap_records_skip_without_claiming_work(dsn: str) -> None:
    schedules = PostgresTaskScheduleStore(dsn, deployment_namespace="cloud")
    firings = PostgresTaskScheduleFiringStore(dsn, deployment_namespace="cloud")
    item, authority = schedule(next_fire_at=datetime.now(UTC) - timedelta(seconds=3))
    schedules.create(item, authority)
    (first,) = firings.claim_due(claimant="scheduler-a", limit=1, claim_ttl_seconds=30)
    dispatched = first.transition(
        ScheduleFiringStatus.DISPATCHED,
        at=first.created_at + timedelta(seconds=1),
        task_id=TaskId(uuid4()),
    )
    firings.settle_firing(
        dispatched,
        expected_status=ScheduleFiringStatus.MATERIALIZING,
        expected_claim_expiry=first.claim_expires_at,
    )
    advanced = schedules.get(item.schedule_id, owner=item.owner)
    assert advanced is not None
    redue_at = datetime.now(UTC) - timedelta(seconds=1)
    redue = TaskSchedule.model_validate(
        {
            **advanced.model_dump(),
            "schedule_version": 2,
            "next_fire_at": redue_at,
            "updated_at": datetime.now(UTC),
        }
    )
    schedules.update(redue, expected_version=1)

    assert firings.claim_due(claimant="scheduler-b", limit=1, claim_ttl_seconds=30) == ()
    with firings.connect() as connection:
        rows = connection.execute(
            "SELECT status, failure_code FROM task_schedule_firings ORDER BY scheduled_for"
        ).fetchall()
    assert rows == [
        {"status": "dispatched", "failure_code": None},
        {"status": "skipped", "failure_code": "overlap_forbidden"},
    ]


@pytest.mark.parametrize(
    ("task_status", "firing_status", "failure_code"),
    [
        ("awaiting_turn", ScheduleFiringStatus.COMPLETED, None),
        ("completed", ScheduleFiringStatus.COMPLETED, None),
        ("failed", ScheduleFiringStatus.FAILED, "task_failed"),
        ("cancelled", ScheduleFiringStatus.FAILED, "task_cancelled"),
    ],
)
def test_terminal_task_reconciles_dispatched_firing_before_overlap(
    dsn: str,
    task_status: str,
    firing_status: ScheduleFiringStatus,
    failure_code: str | None,
) -> None:
    schedules = PostgresTaskScheduleStore(dsn, deployment_namespace="cloud")
    firings = PostgresTaskScheduleFiringStore(dsn, deployment_namespace="cloud")
    item, authority = schedule(next_fire_at=datetime.now(UTC) - timedelta(seconds=2))
    schedules.create(item, authority)
    (claimed,) = firings.claim_due(claimant="scheduler-a", limit=1, claim_ttl_seconds=30)
    task_id = TaskId(uuid4())
    dispatched = claimed.transition(
        ScheduleFiringStatus.DISPATCHED,
        at=claimed.created_at + timedelta(seconds=1),
        task_id=task_id,
    )
    firings.settle_firing(
        dispatched,
        expected_status=ScheduleFiringStatus.MATERIALIZING,
        expected_claim_expiry=claimed.claim_expires_at,
    )
    with firings.connect() as connection:
        connection.execute(
            "INSERT INTO session_streams (deployment_namespace, session_id, current_version) "
            "VALUES (%s, %s, 1)",
            ("cloud", task_id),
        )
        connection.execute(
            "INSERT INTO session_projections (deployment_namespace, session_id, title, status, "
            "created_at, updated_at, current_sequence) VALUES (%s, %s, 'scheduled', %s, "
            "clock_timestamp(), clock_timestamp(), 1)",
            ("cloud", task_id, task_status),
        )

    firings.claim_due(claimant="scheduler-b", limit=10, claim_ttl_seconds=30)

    reconciled = firings.get_firing(claimed.fire_id)
    assert reconciled is not None
    assert reconciled.status is firing_status
    assert reconciled.failure_code == failure_code
    assert reconciled.completed_at is not None
    assert reconciled.claimed_by is None


def test_two_schedulers_create_exactly_one_firing(dsn: str) -> None:
    schedules = PostgresTaskScheduleStore(dsn, deployment_namespace="cloud")
    item, authority = schedule(next_fire_at=datetime.now(UTC) - timedelta(seconds=2))
    schedules.create(item, authority)

    def claim(name: str) -> tuple[object, ...]:
        store = PostgresTaskScheduleFiringStore(dsn, deployment_namespace="cloud")
        return store.claim_due(claimant=name, limit=1, claim_ttl_seconds=30)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(claim, ("scheduler-a", "scheduler-b")))

    assert sum(len(result) for result in results) == 1
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT count(*) FROM task_schedule_firings").fetchone() == (1,)
