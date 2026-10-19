"""Selected revisions are explicit and never promote a Task ceiling into origins."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent_core.application.plugin_resolution import PluginResolver
from agent_core.domain.plugin_snapshots import ExtensionSelection

from tests.agent_storage.test_postgres_plugin_installations import SCOPE, _catalog, _record


def test_empty_selection_does_no_io_and_exact_revision_requires_fixed_package() -> None:
    async def check():
        stores = [AsyncMock() for _ in range(4)]
        resolver = PluginResolver(*stores, allow_mcp=True)
        ceiling = SimpleNamespace(
            skill_components=("permission-only",),
            binding=SimpleNamespace(effective_capabilities={"agent.execute"}),
            tool_profile="general",
            network_profile="mcp-proxy-only",
        )
        empty = await resolver.resolve(
            scope=SCOPE,
            ceiling=ceiling,
            selection=ExtensionSelection(),
            session_id="session-a",
            turn_id="turn-a",
        )
        assert not empty.skills and not empty.plugins
        for store in stores:
            assert not store.mock_calls
        original = _record(enabled=True)
        catalog = _catalog(original.bindings[0].connection)
        original = original.model_copy(
            update={
                "bindings": (
                    original.bindings[0].model_copy(update={"catalog_digest": catalog.digest}),
                )
            }
        )
        stores[0].get.return_value = original
        stores[1].get_mcp.return_value = original.bindings[0].connection
        stores[2].latest.return_value = catalog
        selection = ExtensionSelection.model_validate(
            {"plugins": [{"installation_id": "plugin-a", "revision": 1}]}
        )
        snapshot = await resolver.resolve(
            scope=SCOPE,
            ceiling=ceiling,
            selection=selection,
            session_id="session-a",
            turn_id="turn-a",
        )
        assert not snapshot.direct_mcp and snapshot.mcp[0].catalog_digest == catalog.digest
        stores[3].read.assert_awaited_once_with(original.package)
        stores[0].get.return_value = original.model_copy(update={"revision": 2})
        with pytest.raises(ValueError, match="revision"):
            await resolver.resolve(
                scope=SCOPE,
                ceiling=ceiling,
                selection=selection,
                session_id="session-a",
                turn_id="turn-a",
            )

    asyncio.run(check())


def test_direct_skill_selection_uses_ready_publication_and_exact_task_ceiling() -> None:
    from agent_core.domain.plugin_authority import PluginSelectionRefused
    from agent_core.domain.tool_profiles import ToolProfile

    from tests.agent_tools.test_cloud_skills import Backend

    async def check():
        backend, extensions = Backend(), AsyncMock()
        extensions.get_skill.return_value = backend.installation
        extensions.get_skill_publication.return_value = backend.publication
        ceiling = SimpleNamespace(
            skill_components=(backend.installation.version.skill_id,),
            tool_profile=ToolProfile.GENERAL,
            binding=SimpleNamespace(effective_capabilities={"agent.execute"}),
        )
        resolver = PluginResolver(None, extensions, None, None)
        selection = ExtensionSelection(skills=(backend.installation.installation_id,))
        result = await resolver.resolve(
            scope=backend.installation.scope,
            ceiling=ceiling,
            selection=selection,
            session_id="session-a",
            turn_id="turn-a",
        )
        assert result.direct_skills == (backend.installation.installation_id,)
        assert not result.plugins and result.skills == (backend.installation,)
        ceiling.skill_components = ()
        with pytest.raises(PluginSelectionRefused):
            await resolver.resolve(
                scope=backend.installation.scope,
                ceiling=ceiling,
                selection=selection,
                session_id="session-a",
                turn_id="turn-a",
            )

    asyncio.run(check())


@pytest.mark.parametrize(
    "mode,state", [("api_key", "ready"), ("bearer", "pending"), ("bearer", "expired")]
)
def test_unsupported_or_unusable_mcp_auth_is_refused_before_catalog(mode, state) -> None:
    from agent_core.domain.extensions import McpAuthMode, McpAuthState
    from agent_core.domain.plugin_authority import PluginSelectionRefused

    async def check():
        extensions, catalogs = AsyncMock(), AsyncMock()
        connection = (
            _record()
            .bindings[0]
            .connection.model_copy(
                update={
                    "auth_mode": McpAuthMode(mode),
                    "auth_state": McpAuthState(state),
                    "credential_ref": "credential",
                }
            )
        )
        extensions.get_mcp.return_value = connection
        catalogs.latest.return_value = _catalog(connection)
        ceiling = SimpleNamespace(
            tool_profile="general",
            network_profile="mcp-proxy-only",
            binding=SimpleNamespace(effective_capabilities={"agent.execute"}),
        )
        with pytest.raises(PluginSelectionRefused):
            await PluginResolver(None, extensions, catalogs, None, allow_mcp=True).resolve(
                scope=SCOPE,
                ceiling=ceiling,
                selection=ExtensionSelection(mcp=(connection.connection_id,)),
                session_id="session-a",
                turn_id="turn-a",
            )
        catalogs.latest.assert_not_awaited()

    asyncio.run(check())
