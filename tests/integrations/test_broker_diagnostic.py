"""Sanitization and confirmed diagnostic publication on both transport copies."""

import asyncio
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

MODULES = [("agent_core.contracts.broker_diagnostic", "agent_integrations.rabbitmq")]
try:
    import trench_models  # noqa: F401
except ImportError:
    pass
else:
    MODULES.append(("trench_models.broker_diagnostic", "trench_core.rabbitmq"))

DATA = dict(
    message_type="broker.delivery.rejected",
    schema_version=1,
    rejection_id="01234567-89ab-4cde-8123-0123456789ab",
    deployment_namespace="test",
    consumer_role="trench-turn-executor",
    body_digest="a" * 64,
    byte_count=4,
    error_code="invalid_broker_envelope",
    created_at_ms=1234,
)


@pytest.mark.parametrize("models,transport", MODULES)
@pytest.mark.parametrize(
    "change",
    [
        {"raw": "SECRET"},
        {"message_id": "SECRET"},
        {"schema_version": True},
        {"byte_count": -1},
        {"byte_count": "4"},
        {"error_code": "SECRET"},
        {"consumer_role": "../SECRET"},
        {"deployment_namespace": "\n"},
        {"body_digest": "A" * 64},
        {"rejection_id": "ABC"},
        {"created_at_ms": False},
    ],
)
def test_invalid_before_io(models, transport, change):
    async def run():
        m = importlib.import_module(transport)
        client = m.RabbitMQTransport("amqp://SECRET")
        client._channel = SimpleNamespace(get_exchange=AsyncMock())
        with pytest.raises(m.RabbitMQError) as error:
            await client.publish_diagnostic(
                json.dumps(DATA | change).encode(), exchange="x", routing_key="r"
            )
        assert "SECRET" not in str(error.value)
        client._channel.get_exchange.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("models,transport", MODULES)
def test_strict_bounded_frozen(models, transport):
    m = importlib.import_module(models)
    for raw in (b" " * 4097, b"[" * 2000, b"\xff", b'{"x":1,"x":2}', b"NaN"):
        with pytest.raises(ValueError, match="invalid_broker_diagnostic"):
            m.parse_broker_diagnostic(raw)
    value = m.parse_broker_diagnostic(json.dumps(DATA).encode())
    with pytest.raises(ValueError):
        value.byte_count = 1


@pytest.mark.parametrize("models,transport", MODULES)
@pytest.mark.parametrize("confirmed", [True, False])
def test_confirmed_transport_metadata(models, transport, confirmed):
    async def run():
        m = importlib.import_module(transport)
        target = SimpleNamespace(
            publish=AsyncMock(return_value=m.Basic.Ack() if confirmed else None)
        )
        client = m.RabbitMQTransport("amqp://SECRET")
        client._channel = SimpleNamespace(get_exchange=AsyncMock(return_value=target))
        raw = json.dumps(DATA).encode()
        if confirmed:
            await client.publish_diagnostic(
                raw, exchange="diagnostic", routing_key="delivery.rejected.v1"
            )
        else:
            with pytest.raises(m.RabbitMQError):
                await client.publish_diagnostic(
                    raw, exchange="diagnostic", routing_key="delivery.rejected.v1"
                )
        message = target.publish.call_args.args[0]
        assert message.body == raw and message.message_id == DATA["rejection_id"]
        assert message.correlation_id is None
        assert target.publish.call_args.kwargs["mandatory"] is True

    asyncio.run(run())
