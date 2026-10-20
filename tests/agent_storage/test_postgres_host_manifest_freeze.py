"""ADR-017 admission manifest freeze (real PostgreSQL).

Contract: a Host-bound session with a pinned connector freezes the
connector profile revision's manifest ONCE at admission (get-or-fetch);
the binding carries the real manifest digest and the Worker consumes
the STORED manifest — the gateway builds with live discovery disabled.
Unbound namespaces keep placeholders; pinned-but-unfreezable states
fail closed at admission and at execution.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.host_connectors import (
    HostConnectorBinding,
    HostConnectorProfileVersion,
)
from agent_integrations.host_tools import HostToolGateway
from agent_integrations.host_tools.contracts import HostToolManifest, HostWorkloadIdentity
from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
from agent_storage.postgres.host_manifest_freeze import (
    load_frozen_manifest_by_digest,
    store_frozen_manifest,
)
from agent_storage.postgres.task_admission import load_task_binding
from agent_storage.runtime_composition import CloudCompositionSettings
from zebra_agent_api.factory import create_app

from tests.agent_storage.test_postgres_default_chain_e2e import _settings


def _host_context(namespace: str) -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id=f"grant-{uuid4()}",
        host_app_id=HOST_APP_ID,
        namespace_id=namespace,
        workspace_ref="workspace://freeze",
        resource_refs=(HostResourceRef(resource_type="namespace", resource_id=namespace),),
        scopes=("trench:echo",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=3600,
            max_model_tokens=200_000,
            max_artifact_bytes=1048576,
        ),
        origin="https://host-freeze.example.com",
        policy_version="1",
    )


HOST_APP_ID = "host-freeze"


def _manifest_payload() -> dict[str, object]:
    tools = [
        {
            "name": "host.echo",
            "description": "Echo a bounded payload back from the Host.",
            "requiredArguments": ["message"],
            "argumentProperties": {"message": {"type": "string", "description": "message text"}},
            "parallelSafe": True,
            "capabilityVersion": "1",
            "executionLocation": "host",
            "scopes": ["trench:echo"],
            "risk": "read",
            "timeoutSeconds": 30,
            "maxOutputBytes": 4096,
            "idempotency": "none",
            "receiptSchemaVersion": "1",
        }
    ]
    manifest = HostToolManifest.from_payload(
        {"workloadIdentity": "zebra-worker-freeze", "tools": tools}
    )
    return manifest.to_payload()


def _register_connector(postgres_dsn: str, namespace: str, *, base_uri: str) -> None:
    registry = PostgresHostConnectorRegistry(postgres_dsn, deployment_namespace=namespace)
    registry.publish_profile(
        HostConnectorProfileVersion(
            host_app_id=HOST_APP_ID,
            connector_id="host-freeze-main",
            profile_revision=1,
            base_uri=base_uri,
            manifest_path="/manifest",
            invoke_path_template="/invoke",
            supported_protocol_versions=("v1",),
            workload_identity_ref="zebra-worker-freeze",
            credential_ref="credential/host-freeze",
        )
    )
    registry.bind(
        HostConnectorBinding(
            host_app_id=HOST_APP_ID,
            namespace_id=namespace,
            connector_id="host-freeze-main",
            profile_revision=1,
            binding_revision=1,
        )
    )


def _freeze(postgres_dsn: str, namespace: str, payload: dict[str, object]) -> str:
    digest = str(payload["manifestDigest"])
    store_frozen_manifest(
        postgres_dsn,
        deployment_namespace=namespace,
        manifest_digest=digest,
        connector_id="host-freeze-main",
        profile_revision=1,
        manifest_payload=payload,
    )
    return digest


def _app(postgres_dsn: str, namespace: str, cloud: CloudCompositionSettings, tmp_path):
    from tests.agent_storage.test_postgres_default_chain_e2e import (
        MODEL_KEY_ENV,
    )

    os.environ.setdefault(MODEL_KEY_ENV, "unused")
    settings = _settings("http://127.0.0.1:9", postgres_dsn)
    return create_app(
        database_path=tmp_path / "unused.sqlite",
        settings=settings,
        cloud_composition=cloud,
    )


def _cloud(cloud_composition: CloudCompositionSettings, namespace: str) -> CloudCompositionSettings:
    return CloudCompositionSettings(
        dsn=cloud_composition.dsn,
        deployment_namespace=namespace,
        memory_cursor_signing_key=cloud_composition.memory_cursor_signing_key,
        artifact_objects=cloud_composition.artifact_objects,
        history_scope=cloud_composition.history_scope,
        continuation_scope=cloud_composition.continuation_scope,
    )


def test_manifest_payload_round_trips_through_the_digest() -> None:
    payload = _manifest_payload()
    reborn = HostToolManifest.from_payload(payload)
    assert reborn.digest == payload["manifestDigest"]
    assert reborn.to_payload() == payload


def test_admission_freezes_manifest_digest_into_binding(
    postgres_dsn: str,
    cloud_composition: CloudCompositionSettings,
    namespace: str,
    tmp_path: Path,
) -> None:
    """Pre-stored freeze: the binding carries the REAL digest, no fetch."""
    payload = _manifest_payload()
    digest = _freeze(postgres_dsn, namespace, payload)
    _register_connector(postgres_dsn, namespace, base_uri="https://unreachable.invalid")
    app = _app(postgres_dsn, namespace, _cloud(cloud_composition, namespace), tmp_path)

    response = app.create_session(
        {
            "title": "freeze-e2e",
            "prompt": "freeze probe",
            "workspace": str(tmp_path),
            "execute": False,
        },
        host_context=_host_context(namespace),
    )
    assert response.status_code == 201, response.body
    session_id = str(response.body["session_id"])
    from uuid import UUID

    from agent_core.domain.identifiers import TaskId

    binding = load_task_binding(
        postgres_dsn,
        deployment_namespace=namespace,
        task_id=TaskId(UUID(session_id)),
    )
    assert binding is not None
    assert binding.host_capability.manifest_digest == digest
    assert (
        load_frozen_manifest_by_digest(
            postgres_dsn, deployment_namespace=namespace, manifest_digest=digest
        )
        == payload
    )


def test_pinned_but_unfreezable_admission_fails_closed(
    postgres_dsn: str,
    cloud_composition: CloudCompositionSettings,
    namespace: str,
    tmp_path: Path,
) -> None:
    """Binding + profile but NO stored freeze and an unreachable Host:
    admission refuses — never a placeholder-digest Host session."""
    _register_connector(postgres_dsn, namespace, base_uri="https://127.0.0.1:9")
    app = _app(postgres_dsn, namespace, _cloud(cloud_composition, namespace), tmp_path)

    response = app.create_session(
        {
            "title": "unfreezable-e2e",
            "prompt": "unfreezable probe",
            "workspace": str(tmp_path),
            "execute": False,
        },
        host_context=_host_context(namespace),
    )
    assert response.status_code == 503, response.body
    assert response.body["status"] == "host_manifest_unavailable"


def test_worker_consumes_frozen_manifest_without_live_discovery(
    postgres_dsn: str,
    namespace: str,
    tmp_path: Path,
) -> None:
    """The gateway builds from the STORED manifest with discovery wired
    to raise — proof the execution path no longer live-discovers."""

    from agent_integrations.host_tools import HostToolGateway

    from tests.agent_storage.test_postgres_default_chain_e2e import (
        MODEL_KEY_ENV,
    )

    os.environ.setdefault(MODEL_KEY_ENV, "unused")
    payload = _manifest_payload()
    digest = _freeze(postgres_dsn, namespace, payload)
    _register_connector(postgres_dsn, namespace, base_uri="https://unreachable.invalid")
    from agent_storage.postgres.host_connectors import (
        PostgresHostConnectorRegistry,
    )
    from zebra_agent_worker.host_egress import (
        HostEgressResolver,
    )

    registry = PostgresHostConnectorRegistry(postgres_dsn, deployment_namespace=namespace)
    resolver = HostEgressResolver(registry, None)  # type: ignore[arg-type]
    host_context = _host_context(namespace)
    pinned = resolver.resolve(host_context)
    assert pinned is not None

    original_discover = HostToolGateway.discover

    def _no_live_discovery(self, context):  # noqa: ANN001
        raise AssertionError("live manifest discovery must not run")

    HostToolGateway.discover = _no_live_discovery  # type: ignore[method-assign]
    try:
        from zebra_agent_worker.host_gateway_resolution import (
            frozen_or_discovered_manifest,
        )

        manifest = frozen_or_discovered_manifest(
            HostToolGateway(
                pinned.endpoint,
                HostWorkloadIdentity(pinned.profile.workload_identity_ref, namespace, HOST_APP_ID),
                manifest_binding_policy=pinned.profile.manifest_binding_policy or "legacy",
            ),
            host_context,
            digest,
            lambda d: load_frozen_manifest_by_digest(
                postgres_dsn, deployment_namespace=namespace, manifest_digest=d
            ),
        )
        assert manifest.digest == digest
        assert "host.echo" in {tool.name for tool in manifest.tools}
    finally:
        HostToolGateway.discover = original_discover  # type: ignore[method-assign]


def test_worker_fails_closed_when_free_is_missing(
    postgres_dsn: str,
    namespace: str,
) -> None:
    """A real digest whose frozen row is gone fails closed at execution."""

    from agent_storage.postgres.host_connectors import (
        PostgresHostConnectorRegistry,
    )
    from zebra_agent_worker.host_egress import HostEgressResolver
    from zebra_agent_worker.host_gateway_resolution import (
        frozen_or_discovered_manifest,
    )

    payload = _manifest_payload()
    digest = str(payload["manifestDigest"])  # deliberately NOT stored
    _register_connector(postgres_dsn, namespace, base_uri="https://unreachable.invalid")
    registry = PostgresHostConnectorRegistry(postgres_dsn, deployment_namespace=namespace)
    resolver = HostEgressResolver(registry, None)  # type: ignore[arg-type]
    host_context = _host_context(namespace)
    pinned = resolver.resolve(host_context)
    assert pinned is not None
    with pytest.raises(ValueError, match="frozen Host manifest is missing"):
        frozen_or_discovered_manifest(
            HostToolGateway(
                pinned.endpoint,
                HostWorkloadIdentity(pinned.profile.workload_identity_ref, namespace, HOST_APP_ID),
                manifest_binding_policy=pinned.profile.manifest_binding_policy or "legacy",
            ),
            host_context,
            digest,
            lambda d: None,
        )


@pytest.fixture
def namespace(postgres_dsn: str) -> str:
    """Manifest/connector persistence needs PostgreSQL alone, independent of S3."""
    from agent_storage import bootstrap_control_plane_epoch

    value = f"host-freeze-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=value)
    return value


def test_declared_manifest_db_freeze_admission_recovery_and_neutral_tool(
    postgres_dsn: str,
    namespace: str,
) -> None:
    from types import SimpleNamespace

    from agent_core.domain.identifiers import new_tool_call_id
    from agent_core.domain.tools import ToolCall, ToolCallStatus
    from agent_integrations import ConfiguredHmacHostCredentialResolver
    from agent_integrations.host_tools import HostToolTransportResponse
    from zebra_agent_api.host_manifest_freeze import (
        HostManifestFreezeError,
        resolve_frozen_manifest,
    )
    from zebra_agent_worker.host_gateway_resolution import (
        frozen_or_discovered_manifest,
        resolve_pinned_gateway,
    )
    from zebra_agent_worker.tool_gateway_runtime import WorkerToolGateway

    from tests.agent_integrations.test_host_tools import _FakeTransport
    from tests.worker.test_host_tool_runtime import _Local

    raw = {
        "workloadIdentity": "workload/neutral",
        "tools": [
            {
                "name": "records.read",
                "description": "Read a neutral record",
                "scopes": ["record.read"],
                "argumentProperties": {"query": {"type": "string"}},
                "requiredArguments": ["query"],
                "resourceBindings": [],
            }
        ],
    }
    declared = HostToolManifest.from_payload(raw, binding_policy="declared")
    registry = PostgresHostConnectorRegistry(postgres_dsn, deployment_namespace=namespace)
    profile = HostConnectorProfileVersion(
        host_app_id="neutral-product",
        connector_id="neutral-main",
        profile_revision=2,
        base_uri="https://neutral.invalid",
        manifest_path="/manifest",
        invoke_path_template="/invoke",
        supported_protocol_versions=("v1",),
        workload_identity_ref="workload/neutral",
        credential_ref="credentials/neutral",
        manifest_binding_policy="declared",
    )
    registry.publish_profile(profile)
    registry.bind(
        HostConnectorBinding(
            host_app_id=profile.host_app_id,
            namespace_id=namespace,
            connector_id=profile.connector_id,
            profile_revision=profile.profile_revision,
            binding_revision=1,
        )
    )
    context = _host_context(namespace).model_copy(
        update={
            "host_app_id": "neutral-product",
            "scopes": ("record.read",),
        }
    )
    settings = SimpleNamespace(
        deployment="cloud",
        storage_authority="postgresql",
        database_url=postgres_dsn,
    )
    stores = SimpleNamespace(deployment_namespace=namespace)
    # Old cached bytes cannot be admitted as the declared profile's freeze.
    old = HostToolManifest.from_payload(raw)
    store_frozen_manifest(
        postgres_dsn,
        deployment_namespace=namespace,
        manifest_digest=old.digest,
        connector_id=profile.connector_id,
        profile_revision=1,
        manifest_payload=old.to_payload(),
    )
    store_frozen_manifest(
        postgres_dsn,
        deployment_namespace=namespace,
        manifest_digest=declared.digest,
        connector_id=profile.connector_id,
        profile_revision=2,
        manifest_payload=declared.to_payload(),
    )
    assert resolve_frozen_manifest(settings, stores, context) == declared.to_payload()
    gateway = resolve_pinned_gateway(
        context,
        registry,
        ConfiguredHmacHostCredentialResolver("test-only-key"),
    )
    assert gateway is not None and gateway.manifest_binding_policy == "declared"
    restored = frozen_or_discovered_manifest(
        gateway,
        context,
        declared.digest,
        lambda digest: load_frozen_manifest_by_digest(
            postgres_dsn,
            deployment_namespace=namespace,
            manifest_digest=digest,
        ),
    )
    assert restored.binding_policy == "declared"
    assert restored.resource_bindings_for("records.read") == ()
    gateway.transport = _FakeTransport(
        [HostToolTransportResponse(200, {"output": "neutral record"})]
    )
    worker = WorkerToolGateway(
        local=_Local(),
        host=gateway,
        host_context=context,
        host_manifest=restored,
    )
    assert [tool.name for tool in worker.model_tools] == ["records.read"]
    assert worker.model_tools[0].parameters["properties"] == {"query": {"type": "string"}}
    from datetime import UTC, datetime

    result = worker.execute(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name="records.read",
            arguments={"query": "hello"},
            created_at=datetime.now(UTC),
        )
    )
    assert result.status is ToolCallStatus.EXECUTED and result.output == "neutral record"
    # Pointing a trusted declared profile at an old unmarked cache fails closed.
    profile1 = profile.model_copy(update={"profile_revision": 1})
    registry.publish_profile(profile1)
    registry.bind(
        HostConnectorBinding(
            host_app_id=profile.host_app_id,
            namespace_id=namespace,
            connector_id=profile.connector_id,
            profile_revision=1,
            binding_revision=2,
        )
    )
    with pytest.raises(HostManifestFreezeError, match="binding policy mismatch"):
        resolve_frozen_manifest(settings, stores, context)
