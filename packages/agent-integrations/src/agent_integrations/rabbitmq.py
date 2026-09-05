"""Optional wakeup transport: never business authority or a deduplication store.

Caller owns topology, routing policy and durable DB claim/rejection. Duplicate
physical delivery is intentional; no logical-operation retry is performed.
QoS bounds unacknowledged deliveries only: callers MUST separately bound
handoff/execution slots because ACK releases credit before execution finishes.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import TypeVar

import aio_pika
from agent_core.contracts.broker_diagnostic import parse_broker_diagnostic
from agent_core.contracts.broker_envelope import BrokerEnvelope, parse_broker_envelope
from aio_pika.abc import (
    AbstractChannel,
    AbstractIncomingMessage,
    AbstractQueue,
    AbstractRobustConnection,
)
from aio_pika.connection import make_url
from pamqp.commands import Basic

T = TypeVar("T")


class RabbitMQError(RuntimeError):
    """Sanitized failure; unknown publication outcome is not success."""


async def _bounded(operation: Awaitable[T], timeout: float) -> T:  # noqa: UP047
    try:
        async with asyncio.timeout(timeout):
            return await operation
    except Exception:
        raise RabbitMQError("RabbitMQ operation failed") from None


def _parse(body: bytes) -> BrokerEnvelope:
    try:
        return parse_broker_envelope(body)
    except Exception:
        raise RabbitMQError("invalid broker envelope") from None


class Delivery:
    """Settlement uses the ORIGINAL incoming channel, never a replacement.

    parse() validates shape, not authority. ack() is transport settlement only:
    caller MUST commit durable handoff OR sanitized rejection before calling it.
    Callback return/exception, parse and transport close never ACK automatically.
    Raw invalid messages are not forwarded to a DLQ by this adapter.
    """

    def __init__(self, message: AbstractIncomingMessage, *, timeout: float) -> None:
        self._message = message
        self._timeout = timeout

    @property
    def body(self) -> bytes:
        return self._message.body

    @property
    def redelivered(self) -> bool:
        return bool(self._message.redelivered)

    def parse(self) -> BrokerEnvelope:
        return _parse(self.body)

    async def ack(self) -> None:
        await _bounded(self._message.ack(), self._timeout)

    async def requeue(self) -> None:
        await _bounded(self._message.reject(requeue=True), self._timeout)


class RabbitMQTransport:
    """Explicitly started long-lived robust connection; no autoactivation.

    Lifecycle calls serialize; start/close should bracket publishers/consumers.
    Automatic recovery restores consumers, but never retries a publication.
    """

    def __init__(self, url: str, *, prefetch: int = 16, timeout: float = 10.0) -> None:
        if (
            type(prefetch) is not int
            or not 1 <= prefetch <= 1024
            or type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 0 < timeout <= 300
        ):
            raise ValueError("invalid RabbitMQ prefetch or timeout")
        self._url = url
        self._prefetch = prefetch
        self._timeout = timeout
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._subscriptions: dict[tuple[str, str], AbstractQueue] = {}

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._connection is not None:
                return
            connection = None
            try:
                async with asyncio.timeout(self._timeout):
                    connection = aio_pika.RobustConnection(make_url(self._url))
                    await connection.connect(timeout=self._timeout)
                    channel = await connection.channel(
                        publisher_confirms=True,
                        on_return_raises=True,
                    )
                    await channel.set_qos(prefetch_count=self._prefetch)
                self._connection, self._channel = connection, channel
            except BaseException as error:
                if connection is not None:
                    try:
                        await _bounded(connection.close(), self._timeout)
                    except Exception:
                        pass
                if isinstance(error, asyncio.CancelledError):
                    raise
                if not isinstance(error, Exception):
                    raise
                raise RabbitMQError("RabbitMQ connection failed") from None

    async def close(self) -> None:
        async with self._lifecycle_lock:
            connection = self._connection
            self._connection = self._channel = None
            if connection is not None:
                await _bounded(connection.close(), self._timeout)
            self._subscriptions.clear()

    def _active_channel(self) -> AbstractChannel:
        if self._channel is None:
            raise RabbitMQError("RabbitMQ transport is not started")
        return self._channel

    async def publish(self, raw: bytes, *, exchange: str, routing_key: str) -> None:
        envelope = _parse(raw)
        await self._publish(
            raw, exchange, routing_key, envelope.message_id, envelope.correlation_id
        )

    async def publish_diagnostic(self, raw: bytes, *, exchange: str, routing_key: str) -> None:
        try:
            diagnostic = parse_broker_diagnostic(raw)
        except Exception:
            raise RabbitMQError("invalid broker diagnostic") from None
        await self._publish(raw, exchange, routing_key, diagnostic.rejection_id, None)

    async def _publish(
        self,
        raw: bytes,
        exchange: str,
        routing_key: str,
        message_id: str,
        correlation_id: str | None,
    ) -> None:
        channel = self._active_channel()

        async def send() -> None:
            target = await channel.get_exchange(exchange, ensure=False)
            result = await target.publish(
                aio_pika.Message(
                    body=raw,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    content_type="application/json",
                    message_id=message_id,
                    correlation_id=correlation_id,
                ),
                routing_key=routing_key,
                mandatory=True,
                timeout=self._timeout,
            )
            if not isinstance(result, Basic.Ack):
                raise RabbitMQError("RabbitMQ publish was not confirmed")

        await _bounded(send(), self._timeout)

    async def consume(
        self,
        queue: str,
        handler: Callable[[Delivery], Awaitable[None]],
    ) -> str:
        channel = self._active_channel()

        async def callback(message: AbstractIncomingMessage) -> None:
            try:
                await handler(Delivery(message, timeout=self._timeout))
            except Exception:
                raise RabbitMQError("RabbitMQ delivery handler failed") from None

        async def register() -> str:
            # Passive declaration registers the queue for robust consumer restoration.
            target = await channel.get_queue(queue, ensure=True)
            tag = await target.consume(callback, no_ack=False, timeout=self._timeout)
            self._subscriptions[queue, tag] = target
            return tag

        return await _bounded(register(), self._timeout)

    async def stop_consuming(self, queue: str, consumer_tag: str) -> None:
        """Stop new deliveries; caller drains handlers before closing publishers."""

        async def cancel() -> None:
            target = self._subscriptions.get((queue, consumer_tag))
            if target is None:
                return
            await target.cancel(consumer_tag, timeout=self._timeout)
            self._subscriptions.pop((queue, consumer_tag), None)

        await _bounded(cancel(), self._timeout)
