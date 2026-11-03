"""Verify original operation and fixed profile against shared PostgreSQL."""

from uuid import uuid4

import pytest
from agent_core.domain.runtime_assembly import (
    RuntimeProviderProfile,
    canonical_provider_profile_digest,
)
from agent_core.domain.runtime_bundle_types import BundleScope
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.model_profile_registration import (
    ModelProfileRegistrationConflict,
    PostgresModelProfileRegistrations,
)

from tests.agent_storage.test_postgres_orchestration_admission import dsn as shared_dsn

dsn = shared_dsn


def test_original_operation_and_exact_scope_survive_store_recreation(dsn):
    namespace = str(uuid4())
    scope = BundleScope(
        authority_issuer="https://issuer.example",
        namespace_id=namespace,
        product_id="product",
        environment="test",
        target_id="target",
        deployment_id="deployment",
    )
    payload = {
        "provider": "openai-compatible",
        "base_url": "https://fixture.example/v1",
        "api_key_env": "FIXTURE_KEY",
        "models": ("fixture",),
        "max_context_window_tokens": 1024,
        "max_output_tokens": 128,
    }
    profile = RuntimeProviderProfile.model_validate({
        **payload,
        "pin": {
            "kind": "provider-profile",
            "id": "model-fixture",
            "version": "1.0.0",
            "digest": canonical_provider_profile_digest(payload),
        },
    })
    store = PostgresModelProfileRegistrations(
        PostgresDatabase(dsn, deployment_namespace=namespace)
    )
    original, alias = uuid4(), uuid4()
    store.register(scope, original, "fixture", 1, "request-1", profile)
    restarted = PostgresModelProfileRegistrations(
        PostgresDatabase(dsn, deployment_namespace=namespace)
    )
    restarted.register(scope, original, "fixture", 1, "request-1", profile)
    restarted.register(scope, alias, "fixture", 1, "request-1", profile)
    assert restarted.lookup_operation(scope, original) == restarted.lookup_operation(scope, alias)
    assert restarted.resolve(scope, profile.pin) == profile
    wrong_scope = scope.model_copy(update={"product_id": "other"})
    assert restarted.lookup_operation(wrong_scope, original) is None
    assert restarted.resolve(wrong_scope, profile.pin) is None
    wrong_pin = profile.pin.model_copy(update={"digest": "sha256:" + "0" * 64})
    assert restarted.resolve(scope, wrong_pin) is None

    with pytest.raises(ModelProfileRegistrationConflict):
        restarted.register(scope, uuid4(), "fixture", 1, "different", profile)
    with pytest.raises(ModelProfileRegistrationConflict):
        restarted.register(scope, original, "fixture", 2, "request-2", profile)
    assert restarted.lookup_operation(scope, original)["revision"] == 1
    with restarted.database.connect() as connection:
        row = connection.execute(
            "SELECT count(*) AS count FROM model_profile_revisions WHERE scope_digest = %s",
            (restarted._scope(scope),),
        ).fetchone()
        assert row == {"count": 1}
