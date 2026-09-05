"""Transport boundaries use a fake broker, never a real logical-operation retry."""

import asyncio
import importlib
import json
import tomllib
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

MODULE = "agent_integrations.rabbitmq"
RAW = json.dumps(
    {
        "message_id": "01234567-89ab-4cde-8123-0123456789ab",
        "message_type": "trench.ai.turn.ready",
        "schema_version": 1,
        "deployment_namespace": "dev",
        "scope": {"kind": "principal", "tenant_id": "t", "workspace_id": "w"},
        "aggregate_id": "turn",
        "operation_id": "turn",
        "wake_generation": 0,
        "idempotency_key": "turn:0",
        "correlation_id": "correlation",
        "causation_id": None,
        "occurred_at": "2026-09-04T10:00:00Z",
        "traceparent": None,
        "payload_ref": {"kind": "trench_turn", "id": "turn"},
    }
).encode()


def module():
    assert importlib.util.find_spec(MODULE) is not None, "optional transport is missing"
    return importlib.import_module(MODULE)


def client(monkeypatch):
    m = module()
    exchange = SimpleNamespace(publish=AsyncMock(return_value=m.Basic.Ack()))
    queue = SimpleNamespace(consume=AsyncMock(return_value="consumer"))
    channel = SimpleNamespace(
        set_qos=AsyncMock(),
        get_exchange=AsyncMock(return_value=exchange),
        get_queue=AsyncMock(return_value=queue),
        is_closed=False,
    )
    connection = SimpleNamespace(
        channel=AsyncMock(return_value=channel),
        close=AsyncMock(),
        is_closed=False,
    )
    connect = AsyncMock()
    connection.connect = connect
    monkeypatch.setattr(m.aio_pika, "RobustConnection", Mock(return_value=connection))
    transport = m.RabbitMQTransport("amqp://u:PRIVATE@localhost/vhost", timeout=0.05)
    return m, transport, connection, channel, exchange, queue, connect


def incoming(body=RAW):
    return SimpleNamespace(body=body, redelivered=True, ack=AsyncMock(), reject=AsyncMock())


def test_stop_consumer_cancels_tag_without_closing_publisher(monkeypatch):
    _, transport, connection, channel, _, queue, _ = client(monkeypatch)
    queue.cancel = AsyncMock()
    other = SimpleNamespace(cancel=AsyncMock())
    channel.get_queue.side_effect = lambda name, ensure: queue if ensure else other

    async def check():
        await transport.start()
        await transport.consume("owned-queue", AsyncMock())
        await transport.stop_consuming("owned-queue", "consumer")
        queue.cancel.assert_awaited_once_with("consumer", timeout=0.05)
        other.cancel.assert_not_awaited()
        connection.close.assert_not_awaited()
        await transport.close()

    asyncio.run(check())


def test_cancelled_original_robust_queue_does_not_restore_consumer(monkeypatch):
    from aio_pika.queue import Queue
    from aio_pika.robust_queue import RobustQueue

    _, transport, _, channel, _, _, _ = client(monkeypatch)
    registered = []

    async def consume(self, callback=None, **kwargs):
        registered.append(self)
        self._consumers["tag"] = {"callback": callback}
        return "tag"

    monkeypatch.setattr(RobustQueue, "consume", consume)
    monkeypatch.setattr(RobustQueue, "declare", AsyncMock())
    monkeypatch.setattr(Queue, "cancel", AsyncMock())

    async def check():
        original = RobustQueue(channel, "owned")
        replacement = RobustQueue(channel, "owned")
        channel.get_queue.side_effect = lambda name, ensure: original if ensure else replacement
        await transport.start()
        await transport.consume("owned", AsyncMock())
        await transport.stop_consuming("owned", "tag")
        assert original._consumers == {}
        await original.restore()
        assert registered == [original]
        assert transport._subscriptions == {}
        await transport.close()

    asyncio.run(check())


def test_publish_and_lifecycle(monkeypatch):
    async def run():
        m, transport, connection, channel, exchange, _, connect = client(monkeypatch)
        await transport.start()
        await transport.start()
        assert connect.await_count == 1
        channel.set_qos.assert_awaited_once_with(prefetch_count=16)
        connection.channel.assert_awaited_once_with(
            publisher_confirms=True,
            on_return_raises=True,
        )
        await transport.publish(RAW, exchange="hints", routing_key="turn")
        message = exchange.publish.call_args.args[0]
        assert message.body == RAW and message.message_id == json.loads(RAW)["message_id"]
        assert message.correlation_id == "correlation"
        assert message.delivery_mode == m.aio_pika.DeliveryMode.PERSISTENT
        assert exchange.publish.call_args.kwargs == {
            "routing_key": "turn",
            "mandatory": True,
            "timeout": 0.05,
        }
        await transport.close()
        await transport.close()
        connection.close.assert_awaited_once()
        with pytest.raises(m.RabbitMQError):
            await transport.publish(RAW, exchange="hints", routing_key="turn")

    asyncio.run(run())


@pytest.mark.parametrize("result", ["nack", "none", "false", "return", "timeout", "cancel"])
def test_publish_requires_ack_without_retry(monkeypatch, result):
    async def run():
        m, transport, _, _, exchange, _, _ = client(monkeypatch)
        await transport.start()
        if result == "nack":
            exchange.publish.return_value = m.Basic.Nack()
        elif result in {"none", "false"}:
            exchange.publish.return_value = None if result == "none" else False
        else:
            exchange.publish.side_effect = {
                "return": RuntimeError("PRIVATE body URL"),
                "timeout": TimeoutError("PRIVATE"),
                "cancel": asyncio.CancelledError(),
            }[result]
        error = asyncio.CancelledError if result == "cancel" else m.RabbitMQError
        with pytest.raises(error) as caught:
            await transport.publish(RAW, exchange="hints", routing_key="turn")
        assert "PRIVATE" not in "".join(traceback.format_exception(caught.value))
        assert exchange.publish.await_count == 1

    asyncio.run(run())


def test_invalid_publish_and_manual_delivery(monkeypatch):
    async def run():
        m, transport, _, channel, exchange, queue, _ = client(monkeypatch)
        await transport.start()
        with pytest.raises(m.RabbitMQError):
            await transport.publish(b'{"PRIVATE":', exchange="hints", routing_key="turn")
        exchange.publish.assert_not_called()
        received = []

        async def handler(delivery):
            received.append(delivery)

        assert await transport.consume("turns", handler) == "consumer"
        channel.get_queue.assert_awaited_once_with("turns", ensure=True)
        assert queue.consume.call_args.kwargs["no_ack"] is False
        callback = queue.consume.call_args.args[0]
        message = incoming()
        await callback(message)
        message.ack.assert_not_called()
        assert received[0].redelivered
        assert received[0].parse().operation_id == "turn"
        await received[0].ack()
        message.ack.assert_awaited_once_with()
        bad = incoming(b'{"PRIVATE":')
        await callback(bad)
        assert received[-1].body == bad.body
        with pytest.raises(m.RabbitMQError):
            received[-1].parse()
        bad.ack.assert_not_called()
        await received[-1].requeue()
        bad.reject.assert_awaited_once_with(requeue=True)
        # Explicit settlement also supports a future durable sanitized rejection.
        await received[-1].ack()
        bad.ack.assert_awaited_once_with()

    asyncio.run(run())


def test_stale_settlement_and_callback_failure(monkeypatch):
    async def run():
        m, transport, _, _, _, queue, _ = client(monkeypatch)
        await transport.start()

        async def handler(delivery):
            raise RuntimeError("PRIVATE")

        await transport.consume("turns", handler)
        message = incoming()
        with pytest.raises(m.RabbitMQError) as caught:
            await queue.consume.call_args.args[0](message)
        assert "PRIVATE" not in "".join(traceback.format_exception(caught.value))
        message.ack.assert_not_called()
        delivery = m.Delivery(message, timeout=0.05)
        message.ack.side_effect = RuntimeError("PRIVATE old channel closed")
        await transport.close()
        await transport.start()
        with pytest.raises(m.RabbitMQError):
            await delivery.ack()
        assert message.ack.await_count == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"prefetch": 0},
        {"prefetch": 1025},
        {"prefetch": True},
        {"prefetch": 1.5},
        {"timeout": 0},
        {"timeout": float("inf")},
        {"timeout": float("nan")},
        {"timeout": True},
        {"timeout": 301},
    ],
)
def test_config_bounds(kwargs):
    m = module()
    with pytest.raises(ValueError, match="invalid RabbitMQ"):
        m.RabbitMQTransport("amqp://u:PRIVATE@host/vhost", **kwargs)


@pytest.mark.parametrize("operation", ["publish", "ack", "requeue"])
def test_hung_io_has_finite_deadline(monkeypatch, operation):
    async def run():
        m, transport, _, _, exchange, _, _ = client(monkeypatch)
        await transport.start()

        async def hang(*args, **kwargs):
            await asyncio.Event().wait()

        if operation == "publish":
            exchange.publish.side_effect = hang
            pending = transport.publish(RAW, exchange="hints", routing_key="turn")
        else:
            message = incoming()
            getattr(message, "ack" if operation == "ack" else "reject").side_effect = hang
            pending = getattr(m.Delivery(message, timeout=0.01), operation)()
        with pytest.raises(m.RabbitMQError):
            await asyncio.wait_for(pending, timeout=1)

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["start", "close", "ack", "requeue", "callback"])
def test_cancellation_is_never_converted(monkeypatch, operation):
    async def run():
        m, transport, connection, channel, _, queue, _ = client(monkeypatch)
        if operation == "start":
            channel.set_qos.side_effect = asyncio.CancelledError()
            pending = transport.start()
        else:
            await transport.start()
            message = incoming()
            if operation == "close":
                connection.close.side_effect = asyncio.CancelledError()
                pending = transport.close()
            elif operation == "callback":
                handler = AsyncMock(side_effect=asyncio.CancelledError())
                await transport.consume("turns", handler)
                pending = queue.consume.call_args.args[0](message)
            else:
                getattr(
                    message, "ack" if operation == "ack" else "reject"
                ).side_effect = asyncio.CancelledError()
                pending = getattr(m.Delivery(message, timeout=0.05), operation)()
        with pytest.raises(asyncio.CancelledError):
            await pending
        if operation == "start":
            connection.close.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_initial_connect_failure_leaves_no_background_factory(monkeypatch, cancel):
    async def run():
        m = module()
        from aio_pika.connection import Connection

        entered = asyncio.Event()
        connections = []

        async def hang(self, timeout=None):
            connections.append(self)
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(Connection, "connect", hang)
        transport = m.RabbitMQTransport("amqp://u:PRIVATE@localhost/vhost", timeout=0.01)
        pending = asyncio.create_task(transport.start())
        await asyncio.wait_for(entered.wait(), timeout=1)
        if cancel:
            pending.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else m.RabbitMQError):
            await pending
        await transport.close()
        leaked = [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and "__connection_factory" in task.get_coro().__qualname__
        ]
        # Clean up the intentionally reproduced bug before asyncio.run shutdown.
        for connection in connections:
            await connection.close()
        assert not leaked, "initial connection left a background reconnect factory"

    asyncio.run(run())


def test_client_is_optional_for_production_but_installed_for_tests():
    root = Path(__file__).resolve().parents[2]
    workspace = tomllib.loads((root / "pyproject.toml").read_text())
    package = tomllib.loads((root / "packages/agent-integrations/pyproject.toml").read_text())
    assert "aio-pika==10.0.1" in workspace["dependency-groups"]["dev"]
    assert package["project"]["optional-dependencies"]["rabbitmq"] == ["aio-pika==10.0.1"]


def test_start_cleanup_and_safe_errors(monkeypatch):
    async def run():
        m, transport, connection, channel, _, _, _ = client(monkeypatch)
        channel.set_qos.side_effect = RuntimeError("PRIVATE")
        with pytest.raises(m.RabbitMQError) as caught:
            await transport.start()
        assert "PRIVATE" not in "".join(traceback.format_exception(caught.value))
        connection.close.assert_awaited_once()

    asyncio.run(run())
