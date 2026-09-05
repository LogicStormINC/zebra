"""Deterministic consumer capacity, settlement and synchronous lifetime checks."""

import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent_core.contracts.session_commands import SessionCommandKind
from agent_core.domain.leases import LeaseFence, WorkerLease
from agent_runtime import command_wakeup_consumer as runtime
from agent_storage.postgres.command_wakeup import _canonical_json, _envelope
from agent_storage.postgres.command_wakeup_discovery import PendingCursor
from agent_storage.postgres.command_wakeup_handoff import CommandHandoff, HandoffStatus
from agent_storage.postgres.command_wakeup_pickup import CommandPickup, ResolvedCommand

from tests.agent_storage.test_command_wakeup import _command
from tests.agent_storage.test_postgres_command_wakeup_discovery import SCOPE


class Delivery:
    def __init__(self, body):
        self.body, self.acks, self.requeues = body, 0, 0

    async def ack(self):
        self.acks += 1

    async def requeue(self):
        self.requeues += 1


def _fixture(monkeypatch):
    event = _command()
    now = datetime.now(UTC)
    lease = WorkerLease(
        session_id=event.session_id,
        fence=LeaseFence(control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="worker"),
        acquired_at=now,
        heartbeat_at=now,
        expires_at=now + timedelta(seconds=30),
    )
    body = _canonical_json(_envelope("deployment", event, SCOPE).model_dump(mode="json")).encode()
    monkeypatch.setattr(
        runtime,
        "resolve_command_pickup",
        lambda *a, **k: ResolvedCommand(event.event_id, SCOPE, SessionCommandKind.RUN),
    )
    monkeypatch.setattr(
        runtime,
        "handoff_command",
        lambda *a, **k: CommandHandoff(HandoffStatus.ACCEPTED, uuid4(), event.event_id, lease),
    )
    return event, lease, body


async def _wait(event):
    async with asyncio.timeout(2):
        while not event.is_set():
            await asyncio.sleep(0.001)


async def _quarantine(*args):
    pass


def test_saturated_execution_does_not_block_independent_control_tick(monkeypatch):
    event, lease, body = _fixture(monkeypatch)
    started, release, controlled = Event(), Event(), Event()
    control_id = uuid4()

    def execute(received):
        assert received == lease
        started.set()
        assert release.wait(3)

    monkeypatch.setattr(
        runtime,
        "resolve_command_pickup",
        lambda *a, **k: ResolvedCommand(
            k["accepted_event_id"],
            SCOPE,
            SessionCommandKind.CANCEL
            if k["accepted_event_id"] == control_id
            else SessionCommandKind.RUN,
        ),
    )
    monkeypatch.setattr(
        runtime,
        "discover_command_pickups",
        lambda *a, **k: (CommandPickup(control_id, PendingCursor(datetime.now(UTC), control_id)),),
    )
    monkeypatch.setattr(runtime, "handle_control_command", lambda *a, **k: controlled.set())

    async def scenario():
        consumer = runtime.CommandWakeupConsumer(
            "unused",
            deployment_namespace="deployment",
            owner="worker",
            execute_claimed=execute,
            quarantine=_quarantine,
            execution_slots=1,
        )
        try:
            first = Delivery(body)
            assert await consumer.on_delivery(first) is runtime.PickupOutcome.SCHEDULED
            await _wait(started)
            blocked = Delivery(body)
            assert await consumer.on_delivery(blocked) is runtime.PickupOutcome.DEFERRED
            assert blocked.requeues == 1 and first.acks == 1
            async with asyncio.timeout(1):
                assert await consumer.poll("control") == (runtime.PickupOutcome.ACKNOWLEDGED,)
            assert controlled.is_set()
        finally:
            release.set()
            await consumer.close()

    asyncio.run(scenario())


def test_cancelled_handoff_await_and_shutdown_keep_slot_until_real_execution_finishes(monkeypatch):
    event, lease, body = _fixture(monkeypatch)
    admitting, allow_admit, executing, allow_execute = Event(), Event(), Event(), Event()

    def handoff(*args, **kwargs):
        admitting.set()
        assert allow_admit.wait(3)
        return CommandHandoff(HandoffStatus.ACCEPTED, uuid4(), event.event_id, lease)

    def execute(received):
        executing.set()
        assert allow_execute.wait(3)

    monkeypatch.setattr(runtime, "handoff_command", handoff)

    async def scenario():
        consumer = runtime.CommandWakeupConsumer(
            "unused",
            deployment_namespace="deployment",
            owner="worker",
            execute_claimed=execute,
            quarantine=_quarantine,
            execution_slots=1,
        )
        delivery = Delivery(body)
        pending = asyncio.create_task(consumer.on_delivery(delivery))
        try:
            await _wait(admitting)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            allow_admit.set()
            await _wait(executing)
            assert not consumer._slots.acquire(blocking=False)
            assert delivery.acks == 0
            closing = asyncio.create_task(consumer.close())
            await asyncio.sleep(0)
            assert not closing.done()
            assert await consumer.on_delivery(Delivery(body)) is runtime.PickupOutcome.DEFERRED
            allow_execute.set()
            await closing
            assert consumer._slots.acquire(blocking=False)
        finally:
            allow_admit.set()
            allow_execute.set()
            await consumer.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["schedule", "schedule_value", "database", "quarantine"])
def test_failures_requeue_without_ack_or_false_completion(monkeypatch, failure):
    _, _, body = _fixture(monkeypatch)

    def fail(*args, **kwargs):
        if failure == "schedule_value":
            raise ValueError("executor internal validation failed")
        raise RuntimeError("synthetic private text")

    async def quarantine(*args):
        if failure == "quarantine":
            raise RuntimeError("not durable")
        pytest.fail("scheduling/database errors are not malformed input")

    async def scenario():
        consumer = runtime.CommandWakeupConsumer(
            "unused",
            deployment_namespace="deployment",
            owner="worker",
            execute_claimed=fail,
            quarantine=quarantine,
            execution_slots=1,
        )
        if failure in {"schedule", "schedule_value"}:
            monkeypatch.setattr(consumer._execution, "submit", fail)
        if failure == "database":
            monkeypatch.setattr(runtime, "handoff_command", fail)
        delivery = Delivery(b"invalid" if failure == "quarantine" else body)
        try:
            assert await consumer.on_delivery(delivery) is runtime.PickupOutcome.DEFERRED
            assert delivery.requeues == 1 and delivery.acks == 0
            assert consumer._slots.acquire(blocking=False)
        finally:
            await consumer.close()

    asyncio.run(scenario())


def test_invalid_delivery_ack_waits_for_durable_quarantine(monkeypatch):
    _fixture(monkeypatch)

    async def scenario():
        entered, commit = asyncio.Event(), asyncio.Event()

        async def quarantine(raw, accepted_id, code):
            assert raw == b"invalid" and accepted_id is None and code == "invalid_broker_envelope"
            entered.set()
            await commit.wait()

        consumer = runtime.CommandWakeupConsumer(
            "unused",
            deployment_namespace="deployment",
            owner="worker",
            execute_claimed=lambda lease: None,
            quarantine=quarantine,
        )
        delivery = Delivery(b"invalid")
        try:
            processing = asyncio.create_task(consumer.on_delivery(delivery))
            await entered.wait()
            assert delivery.acks == 0
            commit.set()
            assert await processing is runtime.PickupOutcome.QUARANTINED
            assert delivery.acks == 1
        finally:
            commit.set()
            await consumer.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status", "expected", "acks", "requeues"),
    [
        (runtime.HandoffStatus.SCOPE_DEFERRED, runtime.PickupOutcome.DEFERRED, 0, 1),
        (runtime.HandoffStatus.SCOPE_SETTLED, runtime.PickupOutcome.ACKNOWLEDGED, 1, 0),
    ],
)
def test_stale_broker_hint_yields_to_fallback_then_acks_after_settlement(
    monkeypatch, status, expected, acks, requeues
):
    _, _, body = _fixture(monkeypatch)
    monkeypatch.setattr(
        runtime,
        "handoff_command",
        lambda *a, **k: SimpleNamespace(status=status, lease=None),
    )

    async def scenario():
        consumer = runtime.CommandWakeupConsumer(
            "unused",
            deployment_namespace="deployment",
            owner="worker",
            execute_claimed=lambda lease: pytest.fail("stale hint executed"),
            quarantine=_quarantine,
            scoped_rollout=True,
        )
        try:
            delivery = Delivery(body)
            assert await consumer.on_delivery(delivery) is expected
            assert (delivery.acks, delivery.requeues) == (acks, requeues)
        finally:
            await consumer.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status",
    [HandoffStatus.DUPLICATE, HandoffStatus.RETIRED_NOOP, HandoffStatus.REQUIRES_RECONCILIATION],
)
def test_duplicate_never_schedules_another_execution(monkeypatch, status):
    event, _, body = _fixture(monkeypatch)
    monkeypatch.setattr(
        runtime, "handoff_command", lambda *a, **k: CommandHandoff(status, uuid4(), event.event_id)
    )

    async def scenario():
        consumer = runtime.CommandWakeupConsumer(
            "unused",
            deployment_namespace="deployment",
            owner="worker",
            execute_claimed=lambda lease: pytest.fail("duplicate executed"),
            quarantine=_quarantine,
        )
        try:
            delivery = Delivery(body)
            assert await consumer.on_delivery(delivery) is runtime.PickupOutcome.ACKNOWLEDGED
            assert delivery.acks == 1
        finally:
            await consumer.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "settings",
    [
        {"execution_slots": True},
        {"execution_slots": 33},
        {"batch_size": 0},
        {"lease_ttl": timedelta(0)},
    ],
)
def test_settings_reject_unbounded_configuration(settings):
    with pytest.raises(ValueError):
        runtime.CommandWakeupConsumer(
            "unused",
            deployment_namespace="deployment",
            owner="worker",
            execute_claimed=lambda lease: None,
            quarantine=_quarantine,
            **settings,
        )


def test_full_execution_lane_still_validates_poison_and_advances_bounded_cursor(monkeypatch):
    event, _, _ = _fixture(monkeypatch)
    cursor = PendingCursor(datetime.now(UTC), event.event_id)
    seen, quarantined = [], []

    def discover(*args, **kwargs):
        seen.append(kwargs["after"])
        return () if kwargs["after"] is not None else (CommandPickup(event.event_id, cursor),)

    def invalid(*args, **kwargs):
        raise ValueError("canonical control mislabeled as execution")

    async def quarantine(raw, accepted_id, code):
        assert raw is None
        quarantined.append((accepted_id, code))

    monkeypatch.setattr(runtime, "discover_command_pickups", discover)
    monkeypatch.setattr(runtime, "resolve_command_pickup", invalid)

    async def scenario():
        consumer = runtime.CommandWakeupConsumer(
            "unused",
            deployment_namespace="deployment",
            owner="worker",
            execute_claimed=lambda lease: None,
            quarantine=quarantine,
            execution_slots=1,
            batch_size=1,
        )
        assert consumer._slots.acquire(blocking=False)
        try:
            assert await consumer.poll("execution") == (runtime.PickupOutcome.QUARANTINED,)
            assert await consumer.poll("execution") == ()
            assert await consumer.poll("execution") == (runtime.PickupOutcome.QUARANTINED,)
            assert seen == [None, cursor, None]
            assert len(quarantined) == 2
        finally:
            consumer._slots.release()
            await consumer.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_requeue_waits_for_bounded_delay_and_cancellation_leaves_delivery_unsettled(
    monkeypatch, cancel
):
    _, _, body = _fixture(monkeypatch)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        consumer = runtime.CommandWakeupConsumer(
            "unused",
            deployment_namespace="deployment",
            owner="worker",
            execute_claimed=lambda lease: None,
            quarantine=_quarantine,
            requeue_delay=0.5,
        )
        await consumer.close()

        async def delay(seconds):
            assert seconds == 0.5
            entered.set()
            await release.wait()

        monkeypatch.setattr(runtime.asyncio, "sleep", delay)
        delivery = Delivery(body)
        pending = asyncio.create_task(consumer.on_delivery(delivery))
        await entered.wait()
        assert delivery.acks == delivery.requeues == 0
        if cancel:
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert delivery.acks == delivery.requeues == 0
        else:
            release.set()
            assert await pending is runtime.PickupOutcome.DEFERRED
            assert delivery.requeues == 1 and delivery.acks == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner", "x" * 129),
        ("owner", " spaced "),
        ("deployment_namespace", "bad\nnamespace"),
        ("requeue_delay", 0),
        ("requeue_delay", float("nan")),
    ],
)
def test_identity_and_retry_configuration_fail_before_pool_creation(field, value):
    args = dict(
        deployment_namespace="deployment",
        owner="worker",
        execute_claimed=lambda lease: None,
        quarantine=_quarantine,
    )
    args[field] = value
    with pytest.raises(ValueError):
        runtime.CommandWakeupConsumer("unused", **args)
