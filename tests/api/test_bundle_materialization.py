"""Existing publisher API opts into Bundle v2 without broadening authority."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from agent_core.application.agent_definitions import (
    PublisherGrantCeiling,
    StaticPublisherGrantResolver,
)
from agent_core.domain.agent_definitions import AgentDefinitionScope
from agent_core.domain.bundle_definition import BundleDefinitionVersion
from agent_core.domain.identifiers import AgentDefinitionId, AgentDefinitionVersionId
from agent_storage import sqlite_control_plane_stores
from zebra_agent_api import create_app
from zebra_agent_api.routes import RouteAdapter

from tests.api.test_api_agent_definitions import (
    GRANTED_REFS,
    _definition_payload,
    _host_context,
    _MemoryRegistry,
    _post,
)
from tests.test_bundle_assembly import settings, write_catalog


def setup(tmp_path, *, bundle_grant=True, enabled=True):
    assembly, configured, _ = write_catalog(tmp_path, settings())
    scope = assembly.bundle.manifest.scope
    refs = set(GRANTED_REFS)
    if bundle_grant:
        refs.add("runtime-bundle/" + assembly.bundle.bundle_digest.removeprefix("sha256:") + "@1")
    grant = PublisherGrantCeiling(
        authority_issuer=scope.authority_issuer,
        namespace_id=scope.namespace_id,
        allowed_references=frozenset(refs),
    )
    registry = _MemoryRegistry()
    app = create_app(
        str(tmp_path / "api.sqlite"),
        settings=replace(
            configured, runtime_bundle_config=configured.runtime_bundle_config if enabled else None
        ),
        stores=sqlite_control_plane_stores(tmp_path / "control.sqlite"),
        agent_registry=registry,
        publisher_grants=StaticPublisherGrantResolver({"publisher-b@" + scope.namespace_id: grant}),
    )
    adapter = RouteAdapter(app)
    context = _host_context(scope.namespace_id)
    definition_id = str(uuid4())
    for suffix, payload in (("draft", _definition_payload()), ("draft/validate", {})):
        assert (
            _post(
                adapter,
                f"/agent-definitions/{definition_id}/{suffix}",
                payload,
                host_context=context,
            ).status_code
            == 200
        )
    return assembly, registry, adapter, context, definition_id


def test_native_api_materializes_v2_with_frozen_assembly(tmp_path):
    assembly, registry, adapter, context, definition_id = setup(tmp_path)
    version_id = str(uuid4())
    result = _post(
        adapter,
        f"/agent-definitions/{definition_id}/versions",
        {
            "version_id": version_id,
            "version": 1,
            "runtime_bundle": assembly.bundle.model_dump(mode="json"),
        },
        host_context=context,
    )
    assert result.status_code == 201, result.body
    assert result.body["schema_version"] == "agent-definition/2"
    assert result.body["runtime_assembly"] == assembly.model_dump(mode="json")
    scope = assembly.bundle.manifest.scope
    version = registry.get_version(
        AgentDefinitionScope(
            authority_issuer=scope.authority_issuer,
            namespace_id=scope.namespace_id,
            definition_id=AgentDefinitionId(UUID(definition_id)),
        ),
        AgentDefinitionVersionId(UUID(version_id)),
    )
    assert isinstance(version, BundleDefinitionVersion)
    assert version.runtime_assembly == assembly
    assert "baseline_key" not in str(result.body)


@pytest.mark.parametrize("bundle_grant,enabled,status", [(False, True, 400), (True, False, 400)])
def test_v2_missing_exact_grant_or_operator_catalog_cannot_save(
    tmp_path, bundle_grant, enabled, status
):
    assembly, registry, adapter, context, definition_id = setup(
        tmp_path, bundle_grant=bundle_grant, enabled=enabled
    )
    result = _post(
        adapter,
        f"/agent-definitions/{definition_id}/versions",
        {
            "version_id": str(uuid4()),
            "version": 1,
            "runtime_bundle": assembly.bundle.model_dump(mode="json"),
        },
        host_context=context,
    )
    assert result.status_code == status, result.body
    assert not registry.versions
