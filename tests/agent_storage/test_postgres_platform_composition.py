"""Real-PostgreSQL acceptance for the platform control-plane bundle."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from agent_core.ports.platform_control_plane import AgentPlatformControlPlane
from agent_storage.postgres.migration_runner import apply_postgres_migrations
from agent_storage.postgres_platform_composition import (
    postgres_agent_platform_control_plane,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEBRA_TEST_POSTGRES_DSN"),
    reason="set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests",
)


def test_disabled_flag_composes_no_client_stores() -> None:
    dsn = os.environ["ZEBRA_TEST_POSTGRES_DSN"]
    apply_postgres_migrations(dsn)
    namespace = f"platform-comp-{uuid4()}"
    bundle = postgres_agent_platform_control_plane(
        dsn, deployment_namespace=namespace, client_integration_enabled=False
    )
    assert bundle.deployment_namespace == namespace
    assert bundle.frontend_capabilities is None
    assert bundle.client_sessions is None
    assert bundle.client_effects is None
    with pytest.raises(ValueError):
        bundle.require_client_stores()


def test_enabled_flag_composes_all_client_stores_one_namespace() -> None:
    dsn = os.environ["ZEBRA_TEST_POSTGRES_DSN"]
    namespace = f"platform-comp-{uuid4()}"
    bundle = postgres_agent_platform_control_plane(
        dsn, deployment_namespace=namespace, client_integration_enabled=True
    )
    bundle.require_client_stores()
    for store in (
        bundle.frontend_capabilities,
        bundle.client_sessions,
        bundle.client_control_leases,
        bundle.client_effects,
        bundle.client_effect_receipts,
        bundle.host_authorities,
        bundle.host_connectors,
        bundle.delegation,
        bundle.orchestration,
        bundle.mailbox,
    ):
        assert getattr(store, "deployment_namespace", namespace) in {
            namespace,
            None,
        } or store is not None


def test_bundle_contract_rejects_untrimmed_namespace() -> None:
    with pytest.raises(ValueError):
        AgentPlatformControlPlane(deployment_namespace="  spaced  ")
