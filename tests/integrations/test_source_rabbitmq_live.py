"""Opt-in source-route ACL check against the disposable acceptance broker."""

import asyncio
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("aio_pika")
pytest.importorskip("trench_core.rabbitmq")

from trench_core.rabbitmq import RabbitMQError, RabbitMQTransport
from trench_models.broker_envelope import SourceFetchEnvelope

from scripts.provision_rabbitmq import read_settings, source_topology, topology

ROOT = Path(__file__).resolve().parents[2]
CONTAINER = "rabbitmq-infra-acceptance-rabbitmq-1"
pytestmark = pytest.mark.skipif(
    os.getenv("ZEBRA_RABBITMQ_SOURCE_LIVE") != "1", reason="explicit source live opt-in"
)


@pytest.fixture(scope="module")
def settings():
    result = subprocess.run(
        [
            "docker",
            "inspect",
            CONTAINER,
            "--format",
            '{{index .Config.Labels "com.docker.compose.project"}}',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "rabbitmq-infra-acceptance"
    return read_settings(ROOT / "docker/rabbitmq/.env")


def _url(settings: dict[str, str], user: str, password_key: str) -> str:
    return (
        f"amqp://{user}:{settings[password_key]}@127.0.0.1:"
        f"{settings['RABBITMQ_AMQP_PORT']}/%2Ftrench"
    )


def _source_body() -> bytes:
    command_id = str(uuid4())
    return SourceFetchEnvelope(
        message_id=str(uuid4()),
        schema_version=1,
        message_type="trench.source.fetch.ready",
        deployment_namespace="source-live-acceptance",
        aggregate_id="source-live-acceptance",
        operation_id=command_id,
        wake_generation=0,
        idempotency_key=command_id,
        correlation_id=command_id,
        causation_id=None,
        occurred_at=datetime.now(UTC).isoformat(),
        traceparent=None,
        scope={"kind": "shared_source", "service_scope_id": "public-source-live"},
        payload_ref={"kind": "source_fetch_command", "id": command_id},
    ).model_dump_json().encode()


def test_source_roles_are_route_and_queue_isolated(settings):
    async def denied_consume(url: str, queue: str) -> None:
        transport = RabbitMQTransport(url)
        try:
            await transport.start()
            with pytest.raises(RabbitMQError):
                await transport.consume(queue, asyncio.Queue().put)
        finally:
            await transport.close()

    async def scenario() -> None:
        spec = source_topology()
        relay_url = _url(
            settings, "trench-source-relay", "TRENCH_SOURCE_RABBIT_RELAY_PASSWORD"
        )
        consumer_url = _url(
            settings, "trench-source-consumer", "TRENCH_SOURCE_RABBIT_CONSUMER_PASSWORD"
        )
        old_consumer_url = _url(
            settings, "trench-consumer", "TRENCH_RABBIT_CONSUMER_PASSWORD"
        )
        relay = RabbitMQTransport(relay_url)
        consumer = RabbitMQTransport(consumer_url, prefetch=1)
        deliveries: asyncio.Queue = asyncio.Queue()
        delivery = None
        body = _source_body()
        try:
            await relay.start()
            await consumer.start()
            await consumer.consume(spec["queue"], deliveries.put)
            await relay.publish(body, exchange=spec["exchange"], routing_key=spec["routing_key"])
            delivery = await asyncio.wait_for(deliveries.get(), 5)
            assert delivery.body == body
            await delivery.ack()
            delivery = None
        finally:
            if delivery is not None:
                await delivery.ack()
            await consumer.close()
            await relay.close()

        await denied_consume(old_consumer_url, spec["queue"])
        await denied_consume(consumer_url, topology("trench")["queue"])
        await denied_consume(consumer_url, spec["dlq"])

        wrong_route = RabbitMQTransport(relay_url)
        try:
            await wrong_route.start()
            with pytest.raises(RabbitMQError):
                await wrong_route.publish(
                    _source_body(),
                    exchange=spec["exchange"],
                    routing_key=topology("trench")["routing_key"],
                )
        finally:
            await wrong_route.close()

    asyncio.run(scenario())
