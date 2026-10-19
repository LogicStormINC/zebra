"""Immutable package and binding facts must agree before persistence."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError

from tests.agent_storage.test_postgres_plugin_installations import SCOPE, _record


def test_installation_rejects_cross_scope_or_incomplete_bindings() -> None:
    original = _record()
    values = original.model_dump()
    for bindings in ([], [*values["bindings"], *values["bindings"]]):
        with pytest.raises(ValueError):
            type(original).model_validate({**values, "bindings": bindings})
    values["bindings"][0]["connection"]["scope"] = SCOPE.model_copy(
        update={"namespace_id": "other"}
    )
    with pytest.raises(ValueError, match="another scope"):
        type(original).model_validate(values)


def test_package_digest_covers_index_and_manifest() -> None:
    original = _record()
    values = original.model_dump()
    values["package"]["package_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="package digest"):
        type(original).model_validate(values)


def test_idempotent_install_preserves_original_intent_after_revision_changes() -> None:
    from agent_core.application.plugin_installations import PluginInstallationService

    async def check() -> None:
        original = _record()
        binding = original.bindings[0]
        catalog = McpToolCatalog(
            connection=binding.connection,
            protocol_version="2025-03-26",
            tools=(McpCatalogTool(name="test", input_schema_json='{"type":"object"}'),),
        )
        history = {}
        store = AsyncMock()

        async def get_revision(**kwargs):
            try:
                return history[kwargs["revision"]]
            except KeyError:
                raise ExtensionNotFoundError from None

        async def save(**kwargs):
            history[kwargs["installation"].revision] = kwargs["installation"]

        async def get_creation(**kwargs):
            return await get_revision(**kwargs, revision=1)

        store.get_revision.side_effect = get_revision
        store.get_creation.side_effect = get_creation
        store.get.side_effect = lambda **kwargs: history[max(history)]
        store.save.side_effect = save
        publisher = AsyncMock()
        publisher.publish.return_value = original.package
        extensions = AsyncMock()
        extensions.get_mcp.return_value = binding.connection
        catalogs = AsyncMock()
        catalogs.latest.return_value = catalog
        service = PluginInstallationService(
            store=store,
            extensions=extensions,
            catalogs=catalogs,
            publisher=publisher,
            deployment_namespace="cloud-a",
        )
        payload = {
            "package_digest": original.package.package_digest,
            "bindings": [
                {
                    "kind": "mcp-http",
                    "component_id": "test-mcp",
                    "connection_id": "connection-a",
                }
            ],
        }
        created, fresh = await service.install(
            scope=SCOPE, operated_by="operator", idempotency_key="one", payload=payload
        )
        assert fresh and not created.enabled
        history[2] = created.model_copy(update={"revision": 2, "enabled": True})
        replayed, fresh = await service.install(
            scope=SCOPE, operated_by="operator", idempotency_key="one", payload=payload
        )
        assert not fresh and replayed == history[2]
        no_op = await service.update(
            scope=SCOPE,
            operated_by="operator",
            installation_id=created.installation_id,
            expected_revision=2,
            payload={"enabled": True},
        )
        assert no_op == history[2] and store.save.await_count == 1
        publisher.publish.assert_awaited_once()
        with pytest.raises(ExtensionRevisionConflictError):
            await service.install(
                scope=SCOPE,
                operated_by="operator",
                idempotency_key="one",
                payload={**payload, "package_digest": "sha256:" + "0" * 64},
            )
        publisher.reset_mock()
        extensions.reset_mock()
        disabled = await service.update(
            scope=SCOPE,
            operated_by="operator",
            installation_id=created.installation_id,
            expected_revision=2,
            payload={"enabled": False},
        )
        assert disabled.revision == 3 and not disabled.enabled
        publisher.publish.assert_not_called()
        extensions.get_mcp.assert_not_called()
        with pytest.raises(ValueError):
            await service.install(
                scope=SCOPE,
                operated_by="operator",
                idempotency_key="two",
                payload={**payload, "bundle_root": "/tmp/untrusted"},
            )

    asyncio.run(check())


@pytest.mark.parametrize("change", [{"enabled": False}, {"connection_id": "unrequested"}])
def test_install_rejects_disabled_or_different_component(change: dict[str, object]) -> None:
    from agent_core.application.plugin_installations import PluginInstallationService

    async def check() -> None:
        original = _record()
        connection = original.bindings[0].connection.model_copy(update=change)
        catalog = McpToolCatalog(
            connection=connection,
            protocol_version="2025-03-26",
            tools=(McpCatalogTool(name="test", input_schema_json='{"type":"object"}'),),
        )
        store, extensions, catalogs, publisher = (AsyncMock() for _ in range(4))
        store.get_creation.side_effect = ExtensionNotFoundError
        extensions.get_mcp.return_value = connection
        catalogs.latest.return_value = catalog
        publisher.publish.return_value = original.package
        service = PluginInstallationService(
            store=store,
            extensions=extensions,
            catalogs=catalogs,
            publisher=publisher,
            deployment_namespace="cloud-a",
        )
        with pytest.raises(ExtensionRevisionConflictError):
            await service.install(
                scope=SCOPE,
                operated_by="operator",
                idempotency_key="disabled",
                payload={
                    "package_digest": original.package.package_digest,
                    "bindings": [
                        {
                            "kind": "mcp-http",
                            "component_id": "test-mcp",
                            "connection_id": "connection-a",
                        }
                    ],
                },
            )
        store.save.assert_not_called()

    asyncio.run(check())
