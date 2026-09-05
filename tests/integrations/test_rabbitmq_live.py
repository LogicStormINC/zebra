"""Opt-in destructive tests ONLY for the explicitly named disposable acceptance broker."""

import asyncio
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx
import pytest

pytest.importorskip("aio_pika")
if os.getenv("ZEBRA_RABBITMQ_LIVE_ADAPTER") == "trench":
    from trench_core.rabbitmq import RabbitMQError, RabbitMQTransport
else:
    from agent_integrations.rabbitmq import RabbitMQError, RabbitMQTransport

from scripts.provision_rabbitmq import read_settings, topology

ROOT = Path(__file__).resolve().parents[2]
CONTAINER = "rabbitmq-infra-acceptance-rabbitmq-1"
pytestmark = pytest.mark.skipif(os.getenv("ZEBRA_RABBITMQ_LIVE") != "1", reason="explicit opt-in")


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
    config = read_settings(ROOT / "docker/rabbitmq/.env")
    ports_result = subprocess.run(
        ["docker", "inspect", CONTAINER, "--format", "{{json .NetworkSettings.Ports}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    ports = json.loads(ports_result.stdout)
    for internal, key in (
        ("5672/tcp", "RABBITMQ_AMQP_PORT"),
        ("15672/tcp", "RABBITMQ_MANAGEMENT_PORT"),
        ("15692/tcp", "RABBITMQ_METRICS_PORT"),
    ):
        assert ports[internal] == [{"HostIp": "127.0.0.1", "HostPort": config[key]}]
    return config


def url(settings, system, role):
    user = "provisioner" if role == "admin" else f"{system}-{role}"
    key = (
        "RABBITMQ_ADMIN_PASSWORD"
        if role == "admin"
        else (f"{system.upper()}_RABBIT_{role.upper()}_PASSWORD")
    )
    return f"amqp://{user}:{settings[key]}@127.0.0.1:{settings['RABBITMQ_AMQP_PORT']}/%2F{system}"


def raw(system="zebra"):
    examples = json.loads((ROOT / "docs/contracts/broker-envelope-v1.examples.json").read_text())
    sample = examples["valid"][1 if system == "zebra" else 0]
    sample["message_id"] = str(uuid4())
    return json.dumps(sample).encode()


def management(settings):
    return httpx.Client(
        base_url=f"http://127.0.0.1:{settings['RABBITMQ_MANAGEMENT_PORT']}/api/",
        auth=("provisioner", settings["RABBITMQ_ADMIN_PASSWORD"]),
        trust_env=False,
        timeout=10,
    )


@pytest.fixture(autouse=True)
def empty_acceptance_queues(settings):
    with management(settings) as client:
        for system in ("zebra", "trench"):
            spec = topology(system)
            for queue in (spec["queue"], spec["dlq"]):
                response = client.delete(f"queues/{quote(spec['vhost'], safe='')}/{queue}/contents")
                assert response.status_code == 204


@pytest.mark.parametrize("system", ["zebra", "trench"])
def test_confirm_duplicate_manual_ack_prefetch_and_disconnect(settings, system):
    async def scenario():
        spec = topology(system)
        publisher = RabbitMQTransport(url(settings, system, "relay"))
        consumer = RabbitMQTransport(url(settings, system, "consumer"), prefetch=1)
        deliveries = asyncio.Queue()
        message = raw(system)
        try:
            await publisher.start()
            await consumer.start()
            await consumer.consume(spec["queue"], deliveries.put)
            for _ in range(2):
                await publisher.publish(
                    message, exchange=spec["exchange"], routing_key=spec["routing_key"]
                )
            first = await asyncio.wait_for(deliveries.get(), 5)
            assert first.body == message
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(deliveries.get(), 0.3)
            await first.ack()
            second = await asyncio.wait_for(deliveries.get(), 5)
            assert second.parse().message_id == first.parse().message_id
            await consumer.close()  # No ACK: broker must redeliver, no business retry created.
            consumer = RabbitMQTransport(url(settings, system, "consumer"), prefetch=1)
            await consumer.start()
            await consumer.consume(spec["queue"], deliveries.put)
            redelivered = await asyncio.wait_for(deliveries.get(), 5)
            assert redelivered.redelivered and redelivered.body == message
            await redelivered.ack()
        finally:
            await consumer.close()
            await publisher.close()

    asyncio.run(scenario())


def test_unroutable_and_cross_vhost_fail(settings):
    async def scenario():
        # Administrator is used ONLY to test mandatory-return, bypassing route ACL.
        publisher = RabbitMQTransport(url(settings, "zebra", "admin"))
        try:
            await publisher.start()
            with pytest.raises(RabbitMQError):
                await publisher.publish(raw(), exchange="zebra.command.x", routing_key="missing.v1")
        finally:
            await publisher.close()
        foreign = RabbitMQTransport(
            url(settings, "zebra", "relay").replace("/%2Fzebra", "/%2Ftrench")
        )
        try:
            with pytest.raises(RabbitMQError):
                await foreign.start()
        finally:
            await foreign.close()

    asyncio.run(scenario())


def test_topology_metrics_and_restricted_quarantine(settings):
    with management(settings) as client:
        for system in ("zebra", "trench"):
            spec = topology(system)
            vhost = quote(spec["vhost"], safe="")
            for name in (spec["queue"], spec["dlq"]):
                info = client.get(f"queues/{vhost}/{name}").json()
                assert info["type"] == "quorum" and info["durable"]
            policies = client.get(f"policies/{vhost}").json()
            reliability = next(p for p in policies if p["name"] == "ready-reliability")
            assert reliability["definition"]["dead-letter-strategy"] == "at-least-once"
            assert reliability["definition"]["overflow"] == "reject-publish"
        response = httpx.get(
            f"http://127.0.0.1:{settings['RABBITMQ_METRICS_PORT']}/metrics", trust_env=False
        )
        assert response.status_code == 200 and "rabbitmq_queue_messages" in response.text


def test_quorum_restart_recovers_unacked_and_consumer(settings):
    async def scenario():
        publisher = RabbitMQTransport(url(settings, "zebra", "relay"), timeout=20)
        consumer = RabbitMQTransport(url(settings, "zebra", "consumer"), prefetch=1, timeout=20)
        deliveries = asyncio.Queue()
        message = raw()
        try:
            await publisher.start()
            await consumer.start()
            await consumer.consume("zebra.session.command.ready.q", deliveries.put)
            await publisher.publish(
                message, exchange="zebra.command.x", routing_key="session.command.ready.v1"
            )
            original = await asyncio.wait_for(deliveries.get(), 5)
            process = await asyncio.create_subprocess_exec(
                "docker",
                "restart",
                "--time",
                "10",
                CONTAINER,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            assert await asyncio.wait_for(process.wait(), 45) == 0
            recovered = await asyncio.wait_for(deliveries.get(), 40)
            assert recovered.redelivered and recovered.body == message
            with pytest.raises(RabbitMQError):
                await original.ack()  # Old delivery cannot ACK a new channel's tag.
            await recovered.ack()
            await publisher.publish(
                raw(), exchange="zebra.command.x", routing_key="session.command.ready.v1"
            )
            await (await asyncio.wait_for(deliveries.get(), 5)).ack()
        finally:
            await consumer.close()
            await publisher.close()

    asyncio.run(scenario())


def test_runtime_roles_cannot_read_quarantine_or_publish_foreign_route(settings):
    async def scenario():
        for role, queue in (
            ("consumer", "zebra.session.command.ready.dlq"),
            ("relay", "zebra.session.command.ready.q"),
        ):
            client = RabbitMQTransport(url(settings, "zebra", role))
            try:
                await client.start()
                with pytest.raises(RabbitMQError):
                    await client.consume(queue, asyncio.Queue().put)
            finally:
                await client.close()
        publisher = RabbitMQTransport(url(settings, "zebra", "relay"))
        try:
            await publisher.start()
            with pytest.raises(RabbitMQError):
                await publisher.publish(raw(), exchange="zebra.command.x", routing_key="other.v1")
        finally:
            await publisher.close()

    asyncio.run(scenario())


def test_capacity_rejects_publish_instead_of_dropping_old_work(settings):
    policy_path = "policies/%2Fzebra/ready-reliability"
    with management(settings) as client:
        original = client.get(policy_path).json()
        policy = {key: original[key] for key in ("pattern", "apply-to", "priority", "definition")}
        limited = {**policy, "definition": {**policy["definition"], "max-length-bytes": 1024}}
        assert client.put(policy_path, json=limited).status_code in (201, 204)
        try:

            async def scenario():
                publisher = RabbitMQTransport(url(settings, "zebra", "relay"))
                try:
                    await publisher.start()
                    failed = False
                    for _ in range(30):
                        try:
                            await publisher.publish(
                                raw(),
                                exchange="zebra.command.x",
                                routing_key="session.command.ready.v1",
                            )
                        except RabbitMQError:
                            failed = True
                            break
                    assert failed, "capacity must cause a negative publish outcome"
                finally:
                    await publisher.close()

            asyncio.run(scenario())
        finally:
            assert client.put(policy_path, json=policy).status_code in (201, 204)


def test_delivery_limit_moves_only_test_hint_to_restricted_quarantine(settings):
    async def scenario():
        publisher = RabbitMQTransport(url(settings, "zebra", "relay"))
        consumer = RabbitMQTransport(url(settings, "zebra", "consumer"), prefetch=1)
        deliveries = asyncio.Queue()
        try:
            await publisher.start()
            await consumer.start()
            await consumer.consume("zebra.session.command.ready.q", deliveries.put)
            await publisher.publish(
                raw(), exchange="zebra.command.x", routing_key="session.command.ready.v1"
            )
            count = 0
            while count < 10:
                try:
                    item = await asyncio.wait_for(deliveries.get(), 1)
                except TimeoutError:
                    break
                await item.requeue()
                count += 1
            assert 1 < count < 10
        finally:
            await consumer.close()
            await publisher.close()

    asyncio.run(scenario())
    with management(settings) as client:
        # Management basic.get proves dead-letter arrival without relying on lagged counters.
        result = client.post(
            "queues/%2Fzebra/zebra.session.command.ready.dlq/get",
            json={
                "count": 1,
                "ackmode": "ack_requeue_false",
                "encoding": "auto",
                "truncate": 0,
            },
        )
        assert result.status_code == 200 and len(result.json()) == 1
