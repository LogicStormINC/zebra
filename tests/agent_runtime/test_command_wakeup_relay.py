"""Async relay is opt-in, bounded, nonblocking, and never owns DB locks at publish."""

import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from agent_runtime import command_wakeup_relay as relay
from agent_storage.postgres.command_wakeup_relay import RelayClaim


def _claim():
    return RelayClaim("deployment", uuid4(), "owner", 1, b"canonical", datetime.now(UTC), 1)


def test_db_calls_do_not_block_event_loop_and_network_is_after_claim(monkeypatch):
    started, release = Event(), Event()
    committed = False
    settlements = []

    def claim(*args, **kwargs):
        nonlocal committed
        started.set()
        assert release.wait(2)
        committed = True
        return (_claim(),)

    def settle(*args, **kwargs):
        settlements.append(kwargs["confirmed"])
        return True

    async def publish(body):
        assert committed and body == b"canonical"

    monkeypatch.setattr(relay, "claim_relay_batch", claim)
    monkeypatch.setattr(relay, "settle_relay_claim", settle)

    async def scenario():
        task = asyncio.create_task(relay.relay_command_batch(
            "unused", deployment_namespace="deployment", owner="owner", publish_confirmed=publish))
        try:
            async with asyncio.timeout(1):
                while not started.is_set():
                    await asyncio.sleep(0.001)
            # This coroutine progresses while the synchronous claim is blocked.
            assert not task.done()
        finally:
            release.set()
        assert await task == 1

    asyncio.run(scenario())
    assert settlements == [True]


@pytest.mark.parametrize("outcome", ["error", "timeout", "cancel"])
def test_unknown_outcome_never_marks_published(monkeypatch, outcome):
    settlements = []
    monkeypatch.setattr(relay, "claim_relay_batch", lambda *a, **k: (_claim(),))
    monkeypatch.setattr(relay, "settle_relay_claim",
                        lambda *a, **k: settlements.append(k["confirmed"]) or True)

    async def scenario():
        entered = asyncio.Event()

        async def publish(body):
            entered.set()
            if outcome == "error":
                raise RuntimeError("synthetic secret must not be persisted")
            await asyncio.Event().wait()

        task = asyncio.create_task(relay.relay_command_batch(
            "unused", deployment_namespace="deployment", owner="owner", publish_confirmed=publish,
            publish_timeout=0.05))
        await entered.wait()
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await task == 0

    asyncio.run(scenario())
    assert settlements == ([] if outcome == "cancel" else [False])


@pytest.mark.parametrize("settings", [
    {"batch_size": True}, {"batch_size": 33}, {"publish_timeout": float("nan")},
    {"publish_timeout": 0}, {"lease_ttl": timedelta(seconds=1)},
])
def test_invalid_settings_rejected_before_db(settings):
    async def publish(body):
        raise AssertionError("must not publish")
    with pytest.raises(ValueError, match="settings"):
        asyncio.run(relay.relay_command_batch("unused", deployment_namespace="deployment",
                                             owner="owner", publish_confirmed=publish, **settings))


def test_batch_publications_start_concurrently_and_stay_bounded(monkeypatch):
    monkeypatch.setattr(relay, "claim_relay_batch",
                        lambda *a, **k: tuple(_claim() for _ in range(3)))
    monkeypatch.setattr(relay, "settle_relay_claim", lambda *a, **k: True)

    async def scenario():
        active = 0
        all_started = asyncio.Event()

        async def publish(body):
            nonlocal active
            active += 1
            assert active <= 3
            if active == 3:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), 1)

        assert await relay.relay_command_batch(
            "unused", deployment_namespace="deployment", owner="owner",
            publish_confirmed=publish, batch_size=3,
        ) == 3

    asyncio.run(scenario())


def test_cancellation_during_claim_does_not_publish_or_release_unknown_claim(monkeypatch):
    started, finish, completed = Event(), Event(), Event()

    def claim(*args, **kwargs):
        started.set()
        assert finish.wait(2)
        completed.set()
        return (_claim(),)

    def settle(*args, **kwargs):
        raise AssertionError("cancelled caller must leave the lease recoverable")

    monkeypatch.setattr(relay, "claim_relay_batch", claim)
    monkeypatch.setattr(relay, "settle_relay_claim", settle)

    async def scenario():
        async def publish(body):
            raise AssertionError("cancelled claim must not publish")
        task = asyncio.create_task(relay.relay_command_batch(
            "unused", deployment_namespace="deployment", owner="owner", publish_confirmed=publish))
        try:
            async with asyncio.timeout(1):
                while not started.is_set():
                    await asyncio.sleep(0.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            finish.set()
        assert await asyncio.to_thread(completed.wait, 1)

    asyncio.run(scenario())
