"""Compose one namespace-bound AgentPlatformControlPlane without DDL.

All stores share the same deployment namespace; client stores are only
built when the client integration flag is on. Host authority, connector,
delegation, orchestration, mailbox and agent-registry stores reuse the
existing PostgreSQL adapters so the worker loop stops hand-assembling
them from a raw DSN (ADR-CLIENT-01, CLIENT-PLATFORM-COMP-01).
"""

from __future__ import annotations

from agent_core.ports.platform_control_plane import AgentPlatformControlPlane

from agent_storage.postgres.agent_mailbox import PostgresAgentMailbox
from agent_storage.postgres.agent_registry import PostgresAgentRegistry
from agent_storage.postgres.client_capabilities import (
    PostgresClientCapabilityRegistry,
)
from agent_storage.postgres.client_effects import (
    PostgresClientEffectDispatch,
    PostgresClientEffectReceipts,
)
from agent_storage.postgres.client_sessions import (
    PostgresClientControlLeaseStore,
    PostgresClientSessionRegistry,
)
from agent_storage.postgres.host_auth import PostgresHostAuthorityStore
from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
from agent_storage.postgres.orchestration import PostgresOrchestrationStore
from agent_storage.postgres.subagent_delegation import (
    PostgresSubagentDelegationStore,
)


def postgres_agent_platform_control_plane(
    dsn: str,
    *,
    deployment_namespace: str,
    client_integration_enabled: bool = False,
) -> AgentPlatformControlPlane:
    """Build the platform bundle; adapters never run DDL here."""

    namespace = deployment_namespace
    if client_integration_enabled:
        client_stores = {
            "frontend_capabilities": PostgresClientCapabilityRegistry(
                dsn, deployment_namespace=namespace
            ),
            "client_sessions": PostgresClientSessionRegistry(
                dsn, deployment_namespace=namespace
            ),
            "client_control_leases": PostgresClientControlLeaseStore(
                dsn, deployment_namespace=namespace
            ),
            "client_effects": PostgresClientEffectDispatch(
                dsn, deployment_namespace=namespace
            ),
            "client_effect_receipts": PostgresClientEffectReceipts(
                dsn, deployment_namespace=namespace
            ),
        }
    else:
        client_stores = {
            "frontend_capabilities": None,
            "client_sessions": None,
            "client_control_leases": None,
            "client_effects": None,
            "client_effect_receipts": None,
        }
    return AgentPlatformControlPlane(
        deployment_namespace=namespace,
        host_authorities=PostgresHostAuthorityStore(
            dsn, deployment_namespace=namespace
        ),
        host_connectors=PostgresHostConnectorRegistry(
            dsn, deployment_namespace=namespace
        ),
        agent_registry=PostgresAgentRegistry(dsn, deployment_namespace=namespace),
        orchestration=PostgresOrchestrationStore(
            dsn, deployment_namespace=namespace
        ),
        delegation=PostgresSubagentDelegationStore(
            dsn, deployment_namespace=namespace
        ),
        mailbox=PostgresAgentMailbox(dsn, deployment_namespace=namespace),
        **client_stores,  # type: ignore[arg-type]
    )
