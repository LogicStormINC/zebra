"""Workers verify fixed immutable objects; no API bundle mount or allowlist is needed."""

from pathlib import Path

from agent_integrations.plugins.publication import PluginPackagePublicationService
from agent_storage.postgres.plugin_installations import PostgresPluginInstallationStore
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.cloud_composition import CloudWorkerComposition
from zebra_agent_worker.worker_plugins import WorkerPluginSource


def compose_worker_plugins(
    settings: ZebraAgentSettings, cloud: CloudWorkerComposition | None
) -> WorkerPluginSource | None:
    if not settings.plugins.enabled:
        return None
    if (
        settings.deployment != "cloud"
        or settings.storage_authority != "postgresql"
        or not settings.cloud_extension_worker_enabled
        or cloud is None
        or not cloud.dsn
        or cloud.extension_snapshots is None
        or cloud.skill_objects is None
    ):
        raise ValueError("cloud plugins require composed PostgreSQL extension recovery and objects")
    return WorkerPluginSource(
        PostgresPluginInstallationStore(
            cloud.dsn,
            deployment_namespace=cloud.deployment_namespace,
            task_io_connections=cloud.stores.task_io_connections,
        ),
        PluginPackagePublicationService(
            Path(), (), cloud.skill_objects, cloud.deployment_namespace
        ),
    )
