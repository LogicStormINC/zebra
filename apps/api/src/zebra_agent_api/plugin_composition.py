"""Default-off plugin wiring reuses the Cloud authority and immutable object store."""

from pathlib import Path

from agent_core.application.plugin_installations import PluginInstallationService
from agent_core.application.plugin_resolution import PluginResolver
from agent_core.ports.extensions import ExtensionStore
from agent_integrations.plugins.installation import ApprovedPluginComponents
from agent_integrations.plugins.publication import PluginPackagePublicationService
from agent_security.mcp_credential_protection import mounted_mcp_protector
from agent_storage import CloudCompositionSettings
from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
from agent_storage.postgres.plugin_installations import PostgresPluginInstallationStore
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from agent_storage.postgres.task_io import TaskIoConnections
from agent_tools.skill_publications import SkillPublicationService
from zebra_agent_config import ZebraAgentSettings


def compose_plugins(
    settings: ZebraAgentSettings,
    cloud: CloudCompositionSettings | None,
    extensions: ExtensionStore | None,
    service: PluginInstallationService | None = None,
    *,
    task_io_connections: TaskIoConnections | None = None,
) -> tuple[PluginInstallationService | None, PluginResolver | None]:
    if not settings.plugins.enabled or settings.deployment == "local":
        return service, None
    if service is not None and not settings.cloud_extension_turn_admission_enabled:
        return service, None
    config = settings.plugins
    if (
        settings.deployment != "cloud"
        or settings.storage_authority != "postgresql"
        or not settings.cloud_extensions_manage_enabled
        or not settings.cloud_extension_turn_admission_enabled
        or cloud is None
        or extensions is None
    ):
        raise ValueError("cloud plugins require composed PostgreSQL extensions and Turn admission")
    if (
        not config.bundle_root
        or not Path(config.bundle_root).is_dir()
        or not config.allowed_digests
    ):
        raise ValueError("cloud plugin API requires a trusted bundle root and digest allowlist")
    mcp_available = settings.mcp_credentials.worker_enabled
    if mcp_available:
        config_mcp = settings.mcp_credentials
        mounted_mcp_protector(
            config_mcp.secret_root, config_mcp.key_handle, config_mcp.key_version
        )
    catalogs = PostgresMcpCatalogStore(
        cloud.dsn,
        deployment_namespace=cloud.deployment_namespace,
        task_io_connections=task_io_connections,
    )
    packages = PluginPackagePublicationService(
        Path(config.bundle_root),
        config.allowed_digests,
        cloud.artifact_objects,
        cloud.deployment_namespace,
    )
    if service is None:
        service = PluginInstallationService(
            PostgresPluginInstallationStore(
                cloud.dsn,
                deployment_namespace=cloud.deployment_namespace,
                task_io_connections=task_io_connections,
            ),
            extensions,
            catalogs,
            packages,
            cloud.deployment_namespace,
            mcp_available=mcp_available,
            components=ApprovedPluginComponents(
                packages,
                SkillPublicationService(
                    PostgresSkillPublicationStore(
                        cloud.dsn, deployment_namespace=cloud.deployment_namespace
                    ),
                    cloud.artifact_objects,
                    cloud.deployment_namespace,
                )
                if settings.cloud_skills_publish_enabled
                else None,
                extensions,
                catalogs,
            ),
        )
    return service, PluginResolver(
        service.store,
        extensions,
        catalogs,
        packages,
        allow_mcp=mcp_available,
    )
