"""One-click approved packages reuse scoped publication and configuration operations."""

import io
import zipfile
from dataclasses import dataclass
from hashlib import sha256

from agent_core.application.extension_configuration import set_extension_enabled
from agent_core.application.mcp_connections import mcp_connection_identifier
from agent_core.application.skill_installations import create_skill_installation
from agent_core.domain.extensions import ExtensionScope, SkillInstallation
from agent_core.domain.plugin_installations import (
    PluginBinding,
    PluginMcpBinding,
    PluginPackagePin,
    PluginSkillBinding,
)
from agent_core.domain.plugin_packages import PluginMcpHttpComponent, PluginSkillComponent
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionPageRequest,
    ExtensionRevisionConflictError,
    ExtensionStore,
)
from agent_core.ports.mcp_catalog import McpCatalogStore
from agent_tools.skill_publications import SkillPublicationService

from agent_integrations.plugins.publication import PluginPackagePublicationService


@dataclass(frozen=True)
class ApprovedPluginComponents:
    packages: PluginPackagePublicationService
    publications: SkillPublicationService | None
    extensions: ExtensionStore
    catalogs: McpCatalogStore

    async def prepare(
        self,
        *,
        scope: ExtensionScope,
        package: PluginPackagePin,
    ) -> tuple[PluginBinding, ...]:
        source = await self.packages.read(package)
        bindings: list[PluginBinding] = []
        # Resolve required pre-authorized slots before writing any Skill configuration.
        # A slot is the operator's existing MCP creation key, never a guessed endpoint.
        for component in source.manifest.components:
            if not isinstance(component, PluginMcpHttpComponent):
                continue
            try:
                identifier = mcp_connection_identifier(component.connection_slot)
                connection = await self.extensions.get_mcp(scope=scope, connection_id=identifier)
                catalog = await self.catalogs.latest(
                    scope=scope,
                    connection_id=connection.connection_id,
                    config_revision=connection.revision,
                )
            except ExtensionNotFoundError:
                raise ExtensionRevisionConflictError(
                    "required MCP service is not connected"
                ) from None
            if (
                connection.scope != scope
                or connection.connection_id != identifier
                or not connection.enabled
                or connection.auth_mode.value not in {"none", "bearer"}
                or connection.auth_state.value not in {"not_required", "ready"}
                or catalog.connection != connection
                or not catalog.tools
            ):
                raise ExtensionRevisionConflictError("required MCP service is not ready")
            bindings.append(
                PluginMcpBinding(
                    component_id=component.id,
                    connection=connection,
                    catalog_digest=catalog.digest,
                )
            )

        skills: list[SkillInstallation] = []
        if any(isinstance(item, PluginSkillComponent) for item in source.manifest.components):
            if self.publications is None:
                raise ValueError("Skill publication is unavailable")
            cursor = None
            # ponytail: reuse at most 1,000 scoped installations; add a version lookup
            # port if an operator needs larger per-user catalogs.
            for _ in range(10):
                page = await self.extensions.list_skills(
                    scope=scope,
                    page=ExtensionPageRequest(limit=100, cursor=cursor),
                )
                if any(item.scope != scope for item in page.items):
                    raise ExtensionNotFoundError("foreign Skill installation")
                skills.extend(page.items)
                cursor = page.next_cursor
                if cursor is None:
                    break
            else:
                raise ExtensionRevisionConflictError("Skill installation catalog exceeds limit")

        for component in source.manifest.components:
            if not isinstance(component, PluginSkillComponent):
                continue
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for file in source.files:
                    if file.path.startswith(component.skill_root + "/"):
                        # Fixed ZIP timestamps make uncertain-request recovery byte-identical.
                        info = zipfile.ZipInfo(file.path.removeprefix(component.skill_root + "/"))
                        info.compress_type = zipfile.ZIP_DEFLATED
                        archive.writestr(info, file.content)
            key = (
                "plugin-skill-"
                + sha256(
                    (package.package_digest + ":" + component.id).encode(),
                ).hexdigest()
            )
            assert self.publications is not None
            publication = await self.publications.publish(
                archive=output.getvalue(),
                scope=scope,
                idempotency_key=key,
            )
            matching = [
                item for item in skills if item.enabled and item.version == publication.version
            ]
            if len(matching) > 1:
                raise ExtensionRevisionConflictError("ambiguous Skill installation")
            if matching:
                installation = matching[0]
            else:
                installation, _ = await create_skill_installation(
                    store=self.extensions,
                    scope=scope,
                    idempotency_key=key,
                    payload={
                        "skill_id": publication.version.skill_id,
                        "version_id": publication.version.version_id,
                    },
                )
                if not installation.enabled:
                    if installation.revision != 1:
                        raise ExtensionRevisionConflictError("Skill was explicitly disabled")
                    enabled = await set_extension_enabled(
                        store=self.extensions,
                        scope=scope,
                        kind="skill",
                        object_id=installation.installation_id,
                        expected_revision=1,
                        enabled=True,
                    )
                    assert isinstance(enabled, SkillInstallation)
                    installation = enabled
                skills.append(installation)
            bindings.append(
                PluginSkillBinding(component_id=component.id, installation=installation)
            )
        return tuple(bindings)
