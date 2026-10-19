"""Digest-only installation preserves the same authority, intent and replay checks."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from agent_core.application.plugin_installations import PluginInstallationService
from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError

from tests.agent_storage.test_postgres_plugin_installations import SCOPE, _record


def test_auto_install_rechecks_bindings_and_replays_before_preparing_components() -> None:
    async def check() -> None:
        source = _record()
        binding = source.bindings[0]
        store, extensions, catalogs, publisher, components = (AsyncMock() for _ in range(5))
        records = {}

        async def creation(**kwargs):
            if not records:
                raise ExtensionNotFoundError
            return records[1]

        async def save(**kwargs):
            record = kwargs["installation"]
            records[record.revision] = record

        store.get_creation.side_effect = creation
        store.get.side_effect = lambda **_: records[max(records)]
        store.save.side_effect = save
        publisher.publish.return_value = source.package
        components.prepare.return_value = source.bindings
        extensions.get_mcp.return_value = binding.connection
        catalogs.latest.return_value = McpToolCatalog(
            connection=binding.connection,
            protocol_version="2025-03-26",
            tools=(McpCatalogTool(name="test", input_schema_json='{"type":"object"}'),),
        )
        service = PluginInstallationService(
            store,
            extensions,
            catalogs,
            publisher,
            "cloud-a",
            components,
        )
        request = {"package_digest": source.package.package_digest}
        record, created = await service.install(
            scope=SCOPE,
            operated_by="operator",
            idempotency_key="auto",
            payload=request,
        )
        assert created and not record.enabled
        assert record.bindings[0].connection == binding.connection
        assert record.bindings[0].catalog_digest == catalogs.latest.return_value.digest
        extensions.get_mcp.assert_awaited_once()
        records[2] = record.model_copy(update={"revision": 2, "enabled": True})
        replay, created = await service.install(
            scope=SCOPE,
            operated_by="operator",
            idempotency_key="auto",
            payload=request,
        )
        assert not created and replay == records[2]
        components.prepare.assert_awaited_once()
        publisher.publish.assert_awaited_once()
        with pytest.raises(ExtensionRevisionConflictError):
            await service.install(
                scope=SCOPE,
                operated_by="operator",
                idempotency_key="auto",
                payload={
                    **request,
                    "bindings": [
                        {
                            "component_id": "test-mcp",
                            "kind": "mcp-http",
                            "connection_id": "connection-a",
                        }
                    ],
                },
            )
        # Prepared records cannot bypass the original fresh component authorization.
        records.clear()
        extensions.get_mcp.return_value = binding.connection.model_copy(update={"enabled": False})
        with pytest.raises(ExtensionRevisionConflictError):
            await service.install(
                scope=SCOPE,
                operated_by="operator",
                idempotency_key="new",
                payload=request,
            )
        assert not records

    asyncio.run(check())
