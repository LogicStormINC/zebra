"""Resolve exact installed package sources without creating execution authority."""

from dataclasses import dataclass
from typing import Protocol

from agent_core.domain.extension_snapshots import (
    ExtensionPermissions,
    ExtensionSnapshot,
    ExtensionTaskCeiling,
    McpSnapshotEntry,
)
from agent_core.domain.extensions import ExtensionScope, McpConnection, SkillInstallation
from agent_core.domain.plugin_installations import PluginPackagePin, PluginSkillBinding
from agent_core.domain.plugin_snapshots import ExtensionSelection, PluginSnapshot
from agent_core.domain.tool_profiles import tool_names_for_profile
from agent_core.ports.extensions import ExtensionStore
from agent_core.ports.mcp_catalog import McpCatalogStore
from agent_core.ports.plugin_installations import PluginInstallationStore


class PluginPackageReader(Protocol):
    async def read(self, pin: PluginPackagePin) -> object: ...


@dataclass(frozen=True)
class PluginResolver:
    installations: PluginInstallationStore
    extensions: ExtensionStore
    catalogs: McpCatalogStore
    packages: PluginPackageReader
    allow_mcp: bool = False

    async def resolve(
        self,
        *,
        scope: ExtensionScope,
        ceiling: ExtensionTaskCeiling,
        selection: ExtensionSelection,
        session_id: str,
        turn_id: str,
    ) -> ExtensionSnapshot:
        skills: dict[str, SkillInstallation] = {}
        mcp: dict[str, McpSnapshotEntry] = {}
        plugins: list[PluginSnapshot] = []

        async def skill(identifier: str, expected: SkillInstallation | None = None) -> None:
            if ceiling.tool_profile is None or "skills.read" not in tool_names_for_profile(
                ceiling.tool_profile
            ):
                raise ValueError("selected Skill is outside Task tool profile")
            current = await self.extensions.get_skill(scope=scope, installation_id=identifier)
            if (
                current.scope != scope
                or current.installation_id != identifier
                or not current.enabled
                or current.version.skill_id not in ceiling.skill_components
                or (expected is not None and current != expected)
            ):
                raise ValueError("selected Skill is unavailable or exceeds Task ceiling")
            publication = await self.extensions.get_skill_publication(
                scope=scope,
                skill_id=current.version.skill_id,
                version_id=current.version.version_id,
            )
            if (
                publication.scope != scope
                or publication.version != current.version
                or publication.state != "ready"
            ):
                raise ValueError("selected Skill publication is unavailable")
            if any(
                s.version.skill_id == current.version.skill_id and s != current
                for s in skills.values()
            ):
                raise ValueError("conflicting selected Skill content")
            skills[identifier] = current

        async def connection(
            identifier: str,
            expected: McpConnection | None = None,
            expected_digest: str | None = None,
        ) -> None:
            if not self.allow_mcp or "agent.execute" not in ceiling.binding.effective_capabilities:
                raise ValueError("selected MCP is outside configured Task capabilities")
            if ceiling.tool_profile is None or ceiling.network_profile not in {
                "mcp-proxy-only",
                "full-gateway",
            }:
                raise ValueError("selected MCP is outside Task network profile")
            current = await self.extensions.get_mcp(scope=scope, connection_id=identifier)
            if (
                current.scope != scope
                or current.connection_id != identifier
                or not current.enabled
                or (expected is not None and current != expected)
            ):
                raise ValueError("selected MCP connection is unavailable")
            catalog = await self.catalogs.latest(
                scope=scope, connection_id=identifier, config_revision=current.revision
            )
            if (
                catalog.connection != current
                or not catalog.tools
                or (expected_digest and catalog.digest != expected_digest)
            ):
                raise ValueError("selected MCP catalog is unavailable")
            mcp[identifier] = McpSnapshotEntry(
                connection=current,
                catalog_digest=catalog.digest,
                permissions=ExtensionPermissions(tools=tuple(t.name for t in catalog.tools)),
            )

        for identifier in selection.skills:
            await skill(identifier)
        for identifier in selection.mcp:
            await connection(identifier)
        for selected in selection.plugins:
            current = await self.installations.get(
                scope=scope, installation_id=selected.installation_id
            )
            if (
                current.scope != scope
                or current.installation_id != selected.installation_id
                or current.revision != selected.revision
                or not current.enabled
            ):
                raise ValueError("selected plugin revision is unavailable")
            await self.packages.read(current.package)
            for binding in current.bindings:
                if isinstance(binding, PluginSkillBinding):
                    await skill(binding.installation.installation_id, binding.installation)
                    publication = await self.extensions.get_skill_publication(
                        scope=scope,
                        skill_id=binding.installation.version.skill_id,
                        version_id=binding.installation.version.version_id,
                    )
                    if publication.manifest != current.package.skill_files(binding.component_id):
                        raise ValueError("plugin Skill publication disagrees with package")
                else:
                    await connection(
                        binding.connection.connection_id, binding.connection, binding.catalog_digest
                    )
            plugins.append(PluginSnapshot.from_installation(current))
        if sum(len(item.permissions.tools) for item in mcp.values()) > 32:
            raise ValueError("selected MCP tools exceed execution catalog limit")
        return ExtensionSnapshot(
            scope=scope,
            session_id=session_id,
            turn_id=turn_id,
            skills=tuple(skills.values()),
            mcp=tuple(mcp.values()),
            plugins=tuple(plugins),
            direct_skills=tuple(sorted(selection.skills)),
            direct_mcp=tuple(sorted(selection.mcp)),
        )
