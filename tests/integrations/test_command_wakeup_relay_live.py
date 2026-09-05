"""Explicit isolated PG/Rabbit test; never purge queues or read credential files."""

import asyncio
import os
from urllib.parse import urlsplit

import psycopg
import pytest
from agent_integrations.rabbitmq import RabbitMQTransport
from agent_runtime.command_wakeup_relay import relay_command_batch

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _postgres_dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup_relay import _rows, _seed_outbox

dsn = _dsn_fixture
postgres_dsn = _postgres_dsn_fixture


def _safe_url(value, role):
    try:
        parsed = urlsplit(value)
        if not (parsed.scheme == "amqp" and parsed.hostname == "127.0.0.1"
                and parsed.port == 25672 and parsed.path.lower() == "/%2fzebra"
                and parsed.username == f"zebra-{role}" and parsed.password
                and not parsed.query and not parsed.fragment):
            raise ValueError("unsafe test broker")
    except (ValueError, TypeError):
        raise ValueError("requires explicitly isolated Zebra acceptance broker URL") from None
    return value


@pytest.mark.parametrize("url", [
    "amqp://zebra-relay:fake@localhost:25672/%2Fzebra",
    "amqp://zebra-relay:fake@127.0.0.1:5672/%2Fzebra",
    "amqp://zebra-relay:fake@127.0.0.1:25672/%2Ftrench",
    "amqp://admin:fake@127.0.0.1:25672/%2Fzebra",
    "amqp://zebra-relay:fake@127.0.0.1:25672/%2Fzebra?host=foreign",
])
def test_live_url_guard_rejects_non_fixture_targets(url):
    with pytest.raises(ValueError, match="isolated"):
        _safe_url(url, "relay")


@pytest.mark.skipif(os.getenv("ZEBRA_RABBITMQ_RELAY_LIVE") != "1", reason="explicit relay opt-in")
def test_real_confirm_loss_retries_same_identity_without_holding_db_transaction(dsn):
    relay_url = _safe_url(os.environ.get("ZEBRA_TEST_RABBITMQ_RELAY_URL", ""), "relay")
    consumer_url = _safe_url(os.environ.get("ZEBRA_TEST_RABBITMQ_CONSUMER_URL", ""), "consumer")
    _seed_outbox(dsn)
    row, = _rows(dsn)
    expected = str(row["message_id"])

    def assert_transaction_closed():
        with psycopg.connect(dsn) as connection:
            connection.execute("SELECT message_id FROM broker_outbox FOR UPDATE NOWAIT").fetchall()

    def retry_due():
        with psycopg.connect(dsn) as connection:
            connection.execute("UPDATE broker_outbox SET available_at = clock_timestamp()")

    async def scenario():
        publisher = RabbitMQTransport(relay_url, timeout=3)
        consumer = RabbitMQTransport(consumer_url, prefetch=1, timeout=3)
        deliveries = asyncio.Queue()
        try:
            await publisher.start()
            await consumer.start()
            await consumer.consume("zebra.session.command.ready.q", deliveries.put)
            attempts = 0

            async def publish(body):
                nonlocal attempts
                await asyncio.to_thread(assert_transaction_closed)
                await publisher.publish(body, exchange="zebra.command.x",
                                        routing_key="session.command.ready.v1")
                attempts += 1
                if attempts == 1:
                    # Fault injection after real broker acceptance: caller loses
                    # that confirmation before durable Outbox settlement.
                    raise RuntimeError("injected confirmation loss")

            assert await relay_command_batch(
                dsn, deployment_namespace=NAMESPACE, owner="live-test", publish_confirmed=publish,
                publish_timeout=4,
            ) == 0
            first = await asyncio.wait_for(deliveries.get(), 5)
            if first.parse().message_id != expected:
                await first.requeue()
                raise AssertionError("unrelated message preserved; isolate acceptance queue")
            first_body = first.body
            await first.ack()
            await asyncio.to_thread(retry_due)
            assert await relay_command_batch(
                dsn, deployment_namespace=NAMESPACE, owner="live-test", publish_confirmed=publish,
                publish_timeout=4,
            ) == 1
            second = await asyncio.wait_for(deliveries.get(), 5)
            if second.parse().message_id != expected:
                await second.requeue()
                raise AssertionError("unrelated message preserved; isolate acceptance queue")
            assert second.body == first_body
            await second.ack()
        finally:
            await consumer.close()
            await publisher.close()

    asyncio.run(scenario())
    final, = _rows(dsn)
    assert final["status"] == "published" and final["publish_attempts"] == 2
