"""Opt-in contract against a real supported Redis Agent Memory service."""

from __future__ import annotations

import os
import time
from uuid import uuid4

import pytest
from agent_core.domain.identifiers import MemoryId
from agent_core.ports.agent_memory_gateway import (
    ConfirmedMemoryPublication,
    MemoryGatewayDeleteRequest,
    MemoryGatewaySearchRequest,
    MemoryGatewayStatus,
)
from agent_integrations.redis_agent_memory import (
    RedisAgentMemoryConfig,
    RedisAgentMemoryGateway,
)


def test_live_create_search_get_reconcile_and_delete_contract() -> None:
    if os.environ.get("ZEBRA_TEST_REDIS_AGENT_MEMORY_ALLOW_DATA") != "true":
        pytest.skip("real Redis Agent Memory data export is not explicitly authorized")
    endpoint = os.environ.get("ZEBRA_TEST_REDIS_AGENT_MEMORY_ENDPOINT", "").strip()
    store_id = os.environ.get("ZEBRA_TEST_REDIS_AGENT_MEMORY_STORE_ID", "").strip()
    api_key = os.environ.get("ZEBRA_TEST_REDIS_AGENT_MEMORY_API_KEY", "").strip()
    if not endpoint or not store_id or not api_key:
        pytest.skip("real Redis Agent Memory endpoint, Store ID and API key are required")

    gateway = RedisAgentMemoryGateway(
        RedisAgentMemoryConfig(
            enabled=True,
            base_url=endpoint,
            store_id=store_id,
            api_key=api_key,
            timeout_seconds=15,
        )
    )
    memory_id = MemoryId(uuid4())
    namespace = f"zebra-contract-{uuid4()}"
    publication = ConfirmedMemoryPublication(
        memory_id=memory_id,
        namespace=namespace,
        text=f"Synthetic Zebra contract memory {memory_id}",
        idempotency_key=f"contract-publish:{memory_id}",
    )
    deletion = MemoryGatewayDeleteRequest(
        memory_id=memory_id,
        namespace=namespace,
        idempotency_key=f"contract-delete:{memory_id}",
    )
    try:
        created = gateway.publish(publication)
        replayed = gateway.publish(publication)
        assert created.status is MemoryGatewayStatus.SUCCEEDED
        assert replayed.status is MemoryGatewayStatus.SUCCEEDED
        for _ in range(15):
            recalled = gateway.search(
                MemoryGatewaySearchRequest(
                    namespace=namespace,
                    query=str(memory_id),
                    limit=10,
                )
            )
            if any(hit.memory_id == memory_id for hit in recalled.hits):
                break
            time.sleep(1)
        else:
            pytest.fail("created Redis Agent Memory record was not searchable within 15s")
    finally:
        removed = gateway.delete(deletion)
        assert removed.status in {
            MemoryGatewayStatus.SUCCEEDED,
            MemoryGatewayStatus.NOT_FOUND,
        }
