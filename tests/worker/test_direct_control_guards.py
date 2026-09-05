"""Cloud control must reject missing composition before creating local state."""

from uuid import uuid4

import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_storage.postgres.direct_control import PostgresDirectControl
from zebra_agent_config import load_settings
from zebra_agent_worker.control import SessionControlError, SessionControlService


def test_missing_cloud_stores_cannot_initialize_sqlite(tmp_path):
    settings = load_settings(
        env={
            "ZEBRA_PROFILE": "cloud",
            "ZEBRA_DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused",
            "ZEBRA_RUNTIME_CLASS": "gvisor",
            "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "a" * 64,
            "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
        }
    )
    target = tmp_path / "must-not-exist.sqlite"
    with pytest.raises(SessionControlError, match="explicit stores"):
        SessionControlService(target, settings=settings)
    assert not target.exists()


@pytest.mark.parametrize("key", ["", "secret-marker-" + "x" * 256])
def test_invalid_direct_key_fails_before_connection_without_echo(key):
    control = PostgresDirectControl("unused", deployment_namespace="test")
    scope = OpaqueAuthorityScope(authority_issuer="issuer", namespace_id="tenant")
    with pytest.raises(ValueError) as caught:
        control.cancel(uuid4(), scope=scope, idempotency_key=key)
    assert str(caught.value) == "invalid direct cancellation idempotency key"
