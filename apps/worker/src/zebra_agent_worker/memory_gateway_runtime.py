"""Explicit Redis Agent Memory composition; PostgreSQL remains authoritative."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass

import httpx
from agent_core.domain.memory_delivery import MemoryDeliveryScope
from agent_core.ports.agent_memory_gateway import AgentMemoryGatewayPort
from agent_core.ports.governed_memory_store import GovernedMemoryStorePort
from agent_integrations.redis_agent_memory import (
    RedisAgentMemoryConfig,
    RedisAgentMemoryGateway,
)
from agent_storage.postgres.memory_delivery import PostgresMemoryDeliveryLedger
from zebra_agent_config import MemoryGatewaySettings

from zebra_agent_worker.memory_delivery_consumer import (
    GovernedMemoryDeliveryConsumer,
    MemoryDeliveryConsumption,
)


@dataclass(frozen=True, slots=True)
class MemoryGatewayRuntime:
    gateway: AgentMemoryGatewayPort
    ledger: PostgresMemoryDeliveryLedger
    authority: GovernedMemoryStorePort
    scope: MemoryDeliveryScope
    rollout: str

    def consume_once(self, owner: str) -> MemoryDeliveryConsumption:
        return GovernedMemoryDeliveryConsumer(
            ledger=self.ledger,
            authority=self.authority,
            gateway=self.gateway,
            scope=self.scope,
            owner=owner,
        ).consume_once()


def memory_delivery_scope(
    settings: MemoryGatewaySettings | None,
    *,
    deployment_namespace: str,
) -> MemoryDeliveryScope | None:
    if settings is None or not settings.enabled:
        return None
    assert settings.endpoint is not None and settings.store_id is not None
    identity = "\0".join(
        (
            settings.provider,
            settings.endpoint,
            settings.store_id,
            deployment_namespace,
        )
    )
    return MemoryDeliveryScope(
        deployment_namespace=deployment_namespace,
        scope_digest=hashlib.sha256(identity.encode()).hexdigest(),
        generation=settings.generation,
        revision=0,
    )


def compose_memory_gateway_runtime(
    settings: MemoryGatewaySettings | None,
    *,
    dsn: str,
    deployment_namespace: str,
    authority: GovernedMemoryStorePort,
    scope: MemoryDeliveryScope | None,
    environ: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> MemoryGatewayRuntime | None:
    if settings is None or not settings.enabled:
        return None
    if scope is None:
        raise ValueError("enabled Memory Gateway requires a delivery scope")
    values = os.environ if environ is None else environ
    api_key = values.get(settings.api_key_env, "").strip()
    if not api_key:
        raise ValueError(f"Redis Agent Memory credential is missing: {settings.api_key_env}")
    assert settings.endpoint is not None and settings.store_id is not None
    gateway = RedisAgentMemoryGateway(
        RedisAgentMemoryConfig(
            enabled=True,
            base_url=settings.endpoint,
            store_id=settings.store_id,
            api_key=api_key,
            allow_insecure_http=settings.allow_insecure_http,
            timeout_seconds=settings.timeout_seconds,
        ),
        client=client,
    )
    ledger = PostgresMemoryDeliveryLedger(
        dsn,
        deployment_namespace=deployment_namespace,
    )
    current_scope = ledger.ensure_scope(scope)
    return MemoryGatewayRuntime(
        gateway=gateway,
        ledger=ledger,
        authority=authority,
        scope=current_scope,
        rollout=settings.rollout,
    )
