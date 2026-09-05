"""Deterministic callback confirmation, safe errors and cancellation contract."""

import asyncio
from uuid import uuid4

import pytest
from agent_runtime import command_wakeup_quarantine as runtime
from agent_storage.postgres.command_wakeup_quarantine import RejectionClaim, RejectionReceipt


@pytest.mark.parametrize("failure", ["publish", "false", "settle", "cancel"])
def test_no_callback_success_before_confirmed_fenced_settlement(monkeypatch, failure):
    identity = uuid4()
    claim = RejectionClaim("deployment", "zebra.session.command", identity, "owner", 1, b"safe")
    settlements = []

    def record(*args, **kwargs):
        assert "accepted_event_id" not in kwargs
        return RejectionReceipt(identity, False)

    monkeypatch.setattr(runtime, "record_rejection", record)
    monkeypatch.setattr(runtime, "claim_rejection", lambda *a, **k: claim)
    monkeypatch.setattr(
        runtime,
        "settle_rejection",
        lambda *a, **k: settlements.append(k["confirmed"]) or failure != "settle",
    )

    async def scenario():
        entered = asyncio.Event()

        async def publish(body, **routing):
            assert body == b"safe" and routing["exchange"] == "zebra.command.diagnostic.x"
            entered.set()
            if failure == "publish":
                raise ValueError("secret transport exception")
            if failure == "false":
                return False
            if failure == "cancel":
                await asyncio.Event().wait()

        callback = runtime.CommandWakeupQuarantine(
            "unused", deployment_namespace="deployment", publish_confirmed=publish
        )
        pending = asyncio.create_task(
            callback(b"raw private text", uuid4(), "broker_hint_conflict")
        )
        await entered.wait()
        if failure == "cancel":
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            with pytest.raises(runtime.CommandQuarantineError) as error:
                await pending
            assert "secret" not in str(error.value) and "private" not in str(error.value)

    asyncio.run(scenario())
    assert settlements == ([] if failure == "cancel" else [failure == "settle"])


def test_published_duplicate_never_publishes_again_and_raw_hint_is_ignored(monkeypatch):
    monkeypatch.setattr(
        runtime, "record_rejection", lambda *a, **k: RejectionReceipt(uuid4(), True)
    )

    async def publish(*args, **kwargs):
        pytest.fail("already published")

    callback = runtime.CommandWakeupQuarantine(
        "unused", deployment_namespace="deployment", publish_confirmed=publish
    )
    asyncio.run(callback(b"raw", object(), "invalid_broker_envelope"))
