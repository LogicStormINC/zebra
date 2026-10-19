"""No network: exact approved bytes become real Skill publications and scoped MCP pins."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from agent_core.application.mcp_connections import mcp_connection_identifier
from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionRevisionConflictError,
    SkillInstallationPage,
)
from agent_integrations.plugins.installation import ApprovedPluginComponents
from agent_integrations.plugins.package_integrity import load_plugin_package
from agent_integrations.plugins.publication import PluginPackagePublicationService
from agent_tools.skill_publications import SkillPublicationService

from tests.agent_integrations.test_plugin_publications import Objects
from tests.agent_storage.test_postgres_plugin_installations import SCOPE, _record
from tests.agent_tools.test_skill_publications import Store


def test_components_are_pinned_repeatable_and_never_reenable_explicit_revocation(tmp_path) -> None:
    async def check() -> None:
        root = tmp_path / "input"
        (root / "skills/guide").mkdir(parents=True)
        (root / "skills/guide/SKILL.md").write_text(
            "---\nname: isolated-guide\ndescription: Isolated guide\n"
            "version: 1.0.0\n---\nRead only.\n",
        )
        (root / "plugin.json").write_text(
            json.dumps(
                {
                    "manifest_version": "0.2",
                    "id": "isolated-plugin",
                    "version": "1.0.0",
                    "publisher": "Test",
                    "components": [
                        {"id": "guide", "kind": "skill-bundle", "skill_root": "skills/guide"},
                        {"id": "service", "kind": "mcp-http", "connection_slot": "test-mcp"},
                    ],
                }
            )
        )
        digest = load_plugin_package(root).package_digest
        root.rename(tmp_path / digest.removeprefix("sha256:"))
        objects = Objects()
        packages = PluginPackagePublicationService(tmp_path, (digest,), objects, "cloud-a")
        pin = await packages.publish(package_digest=digest)

        class Publications(Store):
            async def reserve(self, *, idempotency_key=None, **kwargs):
                return await super().reserve(**kwargs)

        publications = Publications()
        extensions, catalogs = AsyncMock(), AsyncMock()
        current, creations = {}, {}

        async def get_skill(**kwargs):
            try:
                return current[kwargs["installation_id"]]
            except KeyError:
                raise ExtensionNotFoundError from None

        async def creation(**kwargs):
            try:
                return creations[kwargs["installation_id"]]
            except KeyError:
                raise ExtensionNotFoundError from None

        async def save(**kwargs):
            item = kwargs["installation"]
            assert item.scope == kwargs["scope"] == SCOPE
            if item.revision == 1:
                creations[item.installation_id] = item
            current[item.installation_id] = item

        extensions.get_skill.side_effect = get_skill
        extensions.get_skill_creation.side_effect = creation
        extensions.save_skill.side_effect = save
        extensions.get_skill_publication.side_effect = lambda **_: publications.current
        extensions.list_skills.side_effect = lambda **_: SkillInstallationPage(
            items=tuple(current.values())
        )
        connection = (
            _record()
            .bindings[0]
            .connection.model_copy(
                update={
                    "connection_id": mcp_connection_identifier("test-mcp"),
                }
            )
        )
        catalog = McpToolCatalog(
            connection=connection,
            protocol_version="2025-03-26",
            tools=(McpCatalogTool(name="test", input_schema_json='{"type":"object"}'),),
        )
        extensions.get_mcp.return_value = connection
        catalogs.latest.return_value = catalog
        installer = ApprovedPluginComponents(
            packages,
            SkillPublicationService(publications, objects, "cloud-a"),
            extensions,
            catalogs,
        )
        first = await installer.prepare(scope=SCOPE, package=pin)
        assert {item.component_id for item in first} == {"guide", "service"}
        skill = next(item for item in first if item.kind == "skill-bundle")
        mcp = next(item for item in first if item.kind == "mcp-http")
        assert skill.installation.enabled and skill.installation.revision == 2
        assert skill.installation.plugin_origin.package_digest == digest
        assert skill.installation.plugin_origin.component_id == "guide"
        assert publications.current.manifest == pin.skill_files("guide")
        assert mcp.connection == connection and mcp.catalog_digest == catalog.digest
        puts = objects.puts
        assert await installer.prepare(scope=SCOPE, package=pin) == first
        assert len(current) == 1 and objects.puts == puts
        # An independently installed matching publication stays a shared origin.
        managed = dict(current)
        shared = skill.installation.model_copy(update={
            "installation_id": "standalone-guide", "plugin_origin": None,
        })
        current.clear()
        current[shared.installation_id] = shared
        saves = extensions.save_skill.await_count
        reused = await installer.prepare(scope=SCOPE, package=pin)
        assert next(item for item in reused if item.kind == "skill-bundle").installation == shared
        assert extensions.save_skill.await_count == saves
        current.clear()
        current.update(managed)
        current[skill.installation.installation_id] = skill.installation.model_copy(
            update={"revision": 3, "enabled": False},
        )
        with pytest.raises(ExtensionRevisionConflictError, match="explicitly disabled"):
            await installer.prepare(scope=SCOPE, package=pin)
        assert not current[skill.installation.installation_id].enabled
        reserves = publications.reserve_count
        extensions.get_mcp.side_effect = ExtensionNotFoundError
        with pytest.raises(ExtensionRevisionConflictError, match="not connected"):
            await installer.prepare(scope=SCOPE, package=pin)
        assert publications.reserve_count == reserves
        extensions.get_mcp.side_effect = None
        extensions.get_mcp.return_value = connection.model_copy(
            update={
                "scope": SCOPE.model_copy(update={"principal_id": "other"}),
            }
        )
        with pytest.raises(ExtensionRevisionConflictError):
            await installer.prepare(scope=SCOPE, package=pin)
        assert publications.reserve_count == reserves

    asyncio.run(check())
