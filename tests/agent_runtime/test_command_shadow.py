"""Shadow transport never mutates command authority and settles durably."""

import asyncio
from types import SimpleNamespace

from agent_runtime import command_shadow as runtime


class Delivery:
    def __init__(self, body: bytes) -> None:
        self.body, self.acks, self.requeues = body, 0, 0

    async def ack(self) -> None:
        self.acks += 1

    async def requeue(self) -> None:
        self.requeues += 1


def test_shadow_relay_publishes_exact_body_and_settles_each_claim(monkeypatch):
    claims = (
        SimpleNamespace(body=b"first"),
        SimpleNamespace(body=b"second"),
    )
    settlements = []
    monkeypatch.setattr(runtime, "claim_command_shadow_batch", lambda *a, **k: claims)
    monkeypatch.setattr(
        runtime,
        "settle_command_shadow",
        lambda dsn, claim, *, confirmed: settlements.append((claim.body, confirmed)) or True,
    )

    async def scenario():
        published = []

        async def publish(body):
            published.append(body)
            if body == b"second":
                raise RuntimeError("private broker failure")

        count = await runtime.relay_command_shadow_batch(
            "dsn",
            deployment_namespace="namespace",
            owner="owner",
            publish_confirmed=publish,
        )
        assert count == 1 and published == [b"first", b"second"]

    asyncio.run(scenario())
    assert settlements == [(b"first", True), (b"second", False)]


def test_shadow_consumer_acks_observation_or_durable_rejection(monkeypatch):
    rejected = []

    def observe(*args, **kwargs):
        if kwargs["body"] == b"invalid":
            raise ValueError

    monkeypatch.setattr(runtime, "observe_command_shadow", observe)
    monkeypatch.setattr(
        runtime,
        "reject_command_shadow",
        lambda *args, **kwargs: rejected.append(kwargs["body"]),
    )

    async def scenario():
        valid, invalid = Delivery(b"valid"), Delivery(b"invalid")
        await runtime.consume_command_shadow(valid, dsn="dsn", deployment_namespace="namespace")
        await runtime.consume_command_shadow(invalid, dsn="dsn", deployment_namespace="namespace")
        assert (valid.acks, valid.requeues) == (1, 0)
        assert (invalid.acks, invalid.requeues) == (1, 0)

    asyncio.run(scenario())
    assert rejected == [b"invalid"]


def test_shadow_consumer_requeues_until_observation_or_rejection_is_durable(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError

    monkeypatch.setattr(runtime, "observe_command_shadow", fail)

    async def scenario():
        delivery = Delivery(b"body")
        await runtime.consume_command_shadow(delivery, dsn="dsn", deployment_namespace="namespace")
        assert (delivery.acks, delivery.requeues) == (0, 1)

    asyncio.run(scenario())
