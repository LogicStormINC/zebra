"""Explicit isolated Rabbit confirms + real PG receipts; no ACL changes or queue purge."""

import asyncio
import os
from uuid import uuid4

import psycopg
import pytest
from agent_core.contracts.broker_diagnostic import parse_broker_diagnostic
from agent_integrations.rabbitmq import RabbitMQTransport
from agent_runtime.command_wakeup_quarantine import CommandQuarantineError, CommandWakeupQuarantine

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_quarantine import _due
from tests.agent_storage.test_postgres_command_wakeup_recovery import _rows
from tests.integrations.test_command_wakeup_relay_live import _safe_url

dsn = _dsn_fixture
postgres_dsn = _pg_fixture


@pytest.mark.skipif(os.getenv("ZEBRA_RABBITMQ_RELAY_LIVE") != "1", reason="explicit relay opt-in")
def test_real_diagnostic_confirm_loss_retries_stable_safe_identity(dsn):
    url = _safe_url(os.environ.get("ZEBRA_TEST_RABBITMQ_RELAY_URL", ""), "relay")
    bodies = []

    def transaction_closed():
        with psycopg.connect(dsn) as connection:
            connection.execute(
                "SELECT rejection_id FROM command_delivery_rejections FOR UPDATE NOWAIT"
            )

    async def scenario():
        transport = RabbitMQTransport(url, timeout=3)
        try:
            await transport.start()

            async def publish(body, **routing):
                await asyncio.to_thread(transaction_closed)
                await transport.publish_diagnostic(body, **routing)
                bodies.append(body)
                if len(bodies) == 1:
                    raise RuntimeError("injected loss after actual broker confirm")

            callback = CommandWakeupQuarantine(
                dsn, deployment_namespace=NAMESPACE, publish_confirmed=publish, publish_timeout=4
            )
            with pytest.raises(CommandQuarantineError):
                await callback(b"synthetic rejected input", uuid4(), "invalid_broker_envelope")
            await asyncio.to_thread(_due, dsn)
            assert await callback.publish_once()
        finally:
            await transport.close()

    asyncio.run(scenario())
    assert len(bodies) == 2 and bodies[0] == bodies[1]
    diagnostic = parse_broker_diagnostic(bodies[0])
    (row,) = _rows(dsn, "command_delivery_rejections")
    assert row["status"] == "published" and row["publish_attempts"] == 2
    assert diagnostic.rejection_id == str(row["rejection_id"])
    # Existing consumer ACL intentionally cannot read the diagnostic queue.
    # This test proves real confirms and PG settlement, not privileged readback.
