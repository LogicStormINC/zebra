"""Artifact preview adapters reuse the existing bounded DNS resolver."""

from typing import Any, cast

import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_storage.postgres.artifact_payloads import PostgresCloudArtifactPayloadStore
from agent_storage.postgres.artifact_reads import PostgresSessionArtifactReadStore
from agent_storage.postgres.delivery_audit import PostgresDeliveryAuditStore
from agent_storage.postgres.task_io import TaskIoConnections
from agent_storage.postgres_composition import postgres_control_plane_stores


def test_artifact_adapters_share_cloud_connector_without_opening_database() -> None:
    dsn = "postgresql://qa:qa@localhost/qa"
    connector = TaskIoConnections(dsn)
    scope = OpaqueAuthorityScope(authority_issuer="https://qa.example", namespace_id="qa")
    stores = postgres_control_plane_stores(
        dsn,
        deployment_namespace="qa",
        memory_cursor_signing_key=b"a" * 32,
        artifact_objects=cast(Any, object()),
        history_scope=scope,
        continuation_scope=scope,
        task_io_connections=connector,
    )
    for adapter in (stores.artifacts, stores.artifact_payloads, stores.delivery_audit):
        assert cast(Any, adapter)._database._task_io is connector
    assert stores.task_io_connections is connector


@pytest.mark.parametrize(
    "adapter_type",
    [
        PostgresSessionArtifactReadStore,
        PostgresCloudArtifactPayloadStore,
        PostgresDeliveryAuditStore,
    ],
)
def test_artifact_adapters_reject_incompatible_connector(adapter_type: Any) -> None:
    connector = TaskIoConnections("postgresql://qa:qa@localhost/other")
    with pytest.raises(ValueError, match="does not match"):
        adapter_type(
            "postgresql://qa:qa@localhost/qa",
            deployment_namespace="qa",
            task_io_connections=connector,
        )
