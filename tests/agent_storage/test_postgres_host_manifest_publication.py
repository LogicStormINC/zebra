"""New admissions select a release while old Task digests remain executable."""

from uuid import uuid4

import pytest
from agent_integrations.host_tools import HostToolManifest

from tests.agent_storage.test_postgres_host_manifest_freeze_revisions import (
    load,
    payload,
    publish,
    store,
)


def test_publication_keeps_old_freeze_and_requires_current_head(postgres_dsn):
    from agent_storage.postgres.host_manifest_freeze import (
        load_frozen_manifest,
        load_frozen_manifest_by_digest,
    )
    from agent_storage.postgres.host_manifest_publication import (
        publish_host_manifest,
    )

    namespace = f"release-{uuid4()}"
    publish(postgres_dsn, namespace, "catalog")
    old, new, later = [payload(name) for name in ("old", "new", "later")]
    store(postgres_dsn, namespace, old)
    profile = dict(deployment_namespace=namespace, host_app_id="catalog",
                   connector_id="main", profile_revision=1)
    assert load_frozen_manifest(postgres_dsn, **profile, prefer_publication=True) == old

    def release(value, expected):
        publish_host_manifest(
            postgres_dsn, **profile, manifest_payload=value,
            manifest_digest=HostToolManifest.from_payload(value).digest,
            expected_manifest_digest=expected["manifestDigest"],
        )

    release(new, old)
    with pytest.raises(ValueError, match="changed"):
        release(later, old)
    assert load_frozen_manifest(postgres_dsn, **profile, prefer_publication=True) == new
    assert load(postgres_dsn, namespace) == old
    for value in (old, new):
        assert load_frozen_manifest_by_digest(
            postgres_dsn, deployment_namespace=namespace,
            manifest_digest=value["manifestDigest"],
        ) == value
    release(old, new)
    assert load_frozen_manifest(postgres_dsn, **profile, prefer_publication=True) == old


def test_new_admission_reaches_provider_wire_without_rebinding_old_task(postgres_dsn):
    from types import SimpleNamespace

    from agent_core.domain.host_connectors import HostConnectorBinding
    from agent_integrations.host_credentials import ConfiguredHmacHostCredentialResolver
    from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
    from agent_storage.postgres.host_manifest_freeze import load_frozen_manifest_by_digest
    from agent_storage.postgres.host_manifest_publication import publish_host_manifest
    from zebra_agent_api.host_manifest_freeze import (
        HostManifestFreezeError,
        resolve_admission_profile,
        resolve_frozen_manifest,
    )
    from zebra_agent_worker.host_gateway_resolution import (
        frozen_or_discovered_manifest,
        resolve_pinned_gateway,
    )
    from zebra_agent_worker.tool_gateway_reachability import host_model_tools

    from tests.agent_integrations.test_deepseek_responses import _gateway
    from tests.worker.test_host_egress import _context

    namespace = f"release-wire-{uuid4()}"
    publish(postgres_dsn, namespace, "catalog")
    context = _context().model_copy(update={"host_app_id": "catalog", "scopes": ("record.read",)})
    registry = PostgresHostConnectorRegistry(postgres_dsn, deployment_namespace=namespace)
    binding = registry.bind(HostConnectorBinding(
        host_app_id=context.host_app_id, namespace_id=context.namespace_id,
        connector_id="main", profile_revision=1, binding_revision=1,
    ))
    old = payload("old")
    store(postgres_dsn, namespace, old)
    old_profile = resolve_admission_profile(postgres_dsn, namespace, context, old["manifestDigest"])
    raw = payload("new")
    raw.pop("manifestDigest")
    raw["tools"][0]["argumentProperties"] = {
        "arguments": {
            "type": "object",
            "properties": {"metric": {"type": "string", "enum": ["count"]}},
            "required": ["metric"],
            "additionalProperties": False,
        },
    }
    manifest = HostToolManifest.from_payload(raw)
    publish_host_manifest(
        postgres_dsn, deployment_namespace=namespace, host_app_id="catalog", connector_id="main",
        profile_revision=1, manifest_payload=manifest.to_payload(), manifest_digest=manifest.digest,
        expected_manifest_digest=old["manifestDigest"],
    )
    settings = SimpleNamespace(
        deployment="cloud", storage_authority="postgresql", database_url=postgres_dsn,
    )
    assert resolve_frozen_manifest(
        settings, SimpleNamespace(deployment_namespace=namespace), context,
    ) == manifest.to_payload()
    assert (
        resolve_admission_profile(postgres_dsn, namespace, context, manifest.digest) == old_profile
    )
    with pytest.raises(HostManifestFreezeError, match="changed"):
        resolve_admission_profile(postgres_dsn, namespace, context, old["manifestDigest"])
    assert registry.resolve_binding(context.host_app_id, context.namespace_id) == binding

    def loader(digest):
        return load_frozen_manifest_by_digest(
            postgres_dsn, deployment_namespace=namespace, manifest_digest=digest,
        )
    gateway = _gateway(lambda _: pytest.fail("must never send a model request"))
    for digest, typed in ((old["manifestDigest"], False), (manifest.digest, True)):
        pinned = resolve_pinned_gateway(
            context, registry, ConfiguredHmacHostCredentialResolver("test-secret"),
        )
        assert pinned is not None
        frozen = frozen_or_discovered_manifest(pinned, context, digest, loader)
        tools = host_model_tools(frozen, context)
        _, body, _, _ = gateway._prepare([], tools=tools, invocation_policy=None, stream=True)
        arguments = body["tools"][0]["parameters"]["properties"].get("arguments")
        assert (arguments is not None and arguments["required"] == ["metric"]) == typed
