"""Real-PostgreSQL acceptance for frontend capability persistence (v31)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.domain.client_capabilities import (
    ClientActionContract,
    ClientActionRisk,
    ClientReadableContract,
    FrontendCapabilityBinding,
    FrontendCapabilityProfileVersion,
    ProfileLifecycle,
)
from agent_storage.postgres.client_capabilities import (
    ClientCapabilityCasError,
    ClientCapabilityConflictError,
    PostgresClientCapabilityRegistry,
)
from agent_storage.postgres.migration_runner import apply_postgres_migrations

pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEBRA_TEST_POSTGRES_DSN"),
    reason="set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests",
)


@pytest.fixture()
def namespace_dsn() -> tuple[str, str]:
    dsn = os.environ["ZEBRA_TEST_POSTGRES_DSN"]
    apply_postgres_migrations(dsn)
    return dsn, f"client-cap-{uuid4()}"


def _registry(dsn: str, namespace: str) -> PostgresClientCapabilityRegistry:
    return PostgresClientCapabilityRegistry(dsn, deployment_namespace=namespace)


def _profile(
    revision: int = 1, action: str = "app.ui.item.open"
) -> FrontendCapabilityProfileVersion:
    return FrontendCapabilityProfileVersion(
        frontend_app_id="fixture-web",
        revision=revision,
        readables=(ClientReadableContract(name="app.ui.route"),),
        actions=(
            ClientActionContract(
                name=action,
                risk=ClientActionRisk.PRESENTATION,
                parameters={
                    "type": "object",
                    "properties": {"itemId": {"type": "string"}},
                    "required": ["itemId"],
                },
            ),
        ),
        published_at=datetime(2026, 8, 25, tzinfo=UTC),
    )


def test_revision_is_insert_only_and_replays_only_identical_digests(
    namespace_dsn: tuple[str, str],
) -> None:
    dsn, namespace = namespace_dsn
    registry = _registry(dsn, namespace)
    profile = _profile()
    registry.publish_profile(profile)
    registry.publish_profile(profile)  # same digest replays
    changed = _profile().model_copy(
        update={"readables": (ClientReadableContract(name="app.ui.other"),)}
    )
    with pytest.raises(ClientCapabilityConflictError):
        registry.publish_profile(changed)
    assert registry.get_profile("fixture-web", 1) is not None
    latest = registry.get_latest_profile("fixture-web")
    assert latest is not None and latest.revision == 1


def test_lifecycle_moves_forward_and_revoked_rejects_new_bindings(
    namespace_dsn: tuple[str, str],
) -> None:
    dsn, namespace = namespace_dsn
    registry = _registry(dsn, namespace)
    profile = _profile()
    registry.publish_profile(profile)
    registry.set_lifecycle("fixture-web", 1, ProfileLifecycle.DEPRECATED)
    registry.set_lifecycle("fixture-web", 1, ProfileLifecycle.REVOKED)
    with pytest.raises(ClientCapabilityConflictError):
        registry.set_lifecycle("fixture-web", 1, ProfileLifecycle.PUBLISHED)
    binding = FrontendCapabilityBinding(
        binding_id=uuid4(),
        deployment_namespace=namespace,
        host_app_id="fixture-host",
        namespace_id="tenant-1",
        frontend_app_id="fixture-web",
        revision=1,
        profile_digest=profile.profile_digest,
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )
    with pytest.raises(ClientCapabilityConflictError):
        registry.save_binding(binding, expected_binding_revision=0)


def test_binding_uses_expected_revision_cas(
    namespace_dsn: tuple[str, str],
) -> None:
    dsn, namespace = namespace_dsn
    registry = _registry(dsn, namespace)
    profile = _profile()
    registry.publish_profile(profile)
    binding = FrontendCapabilityBinding(
        binding_id=uuid4(),
        deployment_namespace=namespace,
        host_app_id="fixture-host",
        namespace_id="tenant-1",
        frontend_app_id="fixture-web",
        revision=1,
        profile_digest=profile.profile_digest,
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )
    registry.save_binding(binding, expected_binding_revision=0)
    bumped = binding.model_copy(update={"binding_revision": 2})
    registry.save_binding(bumped, expected_binding_revision=1)
    with pytest.raises(ClientCapabilityCasError):
        registry.save_binding(bumped, expected_binding_revision=1)
    loaded = registry.get_binding(binding.binding_id)
    assert loaded is not None and loaded.binding_revision == 2


def test_namespaces_are_isolated(namespace_dsn: tuple[str, str]) -> None:
    dsn, namespace = namespace_dsn
    other = f"client-cap-{uuid4()}"
    first = _registry(dsn, namespace)
    second = _registry(dsn, other)
    first.publish_profile(_profile())
    assert second.get_profile("fixture-web", 1) is None
