"""Opt-in PostgreSQL extensions sharing the control plane's cloud authority."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_core.ports.extensions import ExtensionStore
from agent_runtime.mcp_catalog_refresh import McpCatalogRefresh
from agent_security.mcp_credential_management import McpCredentialManagement
from agent_storage import (
    CloudCompositionSettings,
    ControlPlaneStores,
    PostgresControlPlaneStores,
    cloud_composition_from_environment,
)
from agent_storage.postgres.extension_snapshots import PostgresExtensionSnapshotStore
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
from agent_storage.postgres.mcp_credentials import PostgresMcpCredentialStore
from agent_storage.postgres.migration_runner import require_current_schema
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from agent_tools.skill_publications import SkillPublicationService
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission
from zebra_agent_api.mcp_credential_composition import compose_mcp_credentials

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi


def resolve_publication_cloud(
    settings: ZebraAgentSettings,
    stores: ControlPlaneStores | None,
    cloud: CloudCompositionSettings | None,
    extension_store: ExtensionStore | None,
    service: SkillPublicationService | None,
    credentials: McpCredentialManagement | None = None,
    refresh: McpCatalogRefresh | None = None,
) -> CloudCompositionSettings | None:
    """Resolve once before control-plane creation; explicit services remain caller-owned."""
    if settings.mcp_credentials.refresh_enabled and refresh is None:
        if not settings.mcp_credentials.enabled or credentials is not None:
            raise ValueError("automatic MCP refresh requires automatically composed credentials")
    if settings.mcp_credentials.enabled and credentials is None:
        if (
            settings.deployment == "local"
            or settings.storage_authority != "postgresql"
            or not settings.cloud_extensions_read_enabled
            or not settings.cloud_extensions_manage_enabled
        ):
            raise ValueError(
                "MCP credential composition requires cloud PostgreSQL extension reads/manage"
            )
        if stores is not None or extension_store is not None:
            raise ValueError(
                "automatic MCP credentials require composed control plane and extensions"
            )
        cloud = cloud if cloud is not None else cloud_composition_from_environment()
    if (
        settings.deployment == "local"
        or not settings.cloud_skills_publish_enabled
        or service is not None
    ):
        return cloud
    if not settings.cloud_extensions_read_enabled:
        raise ValueError("cloud skill publication requires extension reads enabled")
    if settings.storage_authority != "postgresql":
        raise ValueError("cloud skill publication requires PostgreSQL storage")
    if stores is not None or extension_store is not None:
        raise ValueError(
            "automatic skill publication requires composed control plane and extensions"
        )
    return cloud if cloud is not None else cloud_composition_from_environment()


def compose_http_extensions(
    settings: ZebraAgentSettings,
    api: ZebraAgentApi,
    *,
    cloud_composition: CloudCompositionSettings | None,
    extension_store: ExtensionStore | None,
    service: SkillPublicationService | None,
    credentials: McpCredentialManagement | None = None,
    refresh: McpCatalogRefresh | None = None,
) -> tuple[
    ExtensionStore | None,
    SkillPublicationService | None,
    McpCredentialManagement | None,
    McpCatalogRefresh | None,
]:
    """Admit reads first, then reuse their schema admission for publication metadata."""
    stores = None
    if (
        settings.deployment != "local"
        and settings.cloud_extensions_read_enabled
        and extension_store is None
    ):
        stores = api.stores
    extension = compose_extension_store(
        settings,
        stores,
        cloud_composition=cloud_composition,
        extension_store=extension_store,
    )
    if settings.deployment != "local" and settings.cloud_skills_publish_enabled and service is None:
        if cloud_composition is None:
            raise ValueError("cloud skill publication requires resolved cloud composition")
        service = SkillPublicationService(
            store=PostgresSkillPublicationStore(
                cloud_composition.dsn,
                deployment_namespace=cloud_composition.deployment_namespace,
            ),
            objects=cloud_composition.artifact_objects,
            deployment_namespace=cloud_composition.deployment_namespace,
        )
    if settings.mcp_credentials.enabled and credentials is None:
        if cloud_composition is None:
            raise ValueError("MCP credentials require resolved cloud composition")
        credentials = compose_mcp_credentials(settings, cloud_composition)
    if settings.mcp_credentials.refresh_enabled and refresh is None:
        if (
            cloud_composition is None
            or credentials is None
            or not isinstance(credentials.store, PostgresMcpCredentialStore)
        ):
            raise ValueError("MCP refresh requires composed PostgreSQL credentials")
        refresh = McpCatalogRefresh(
            credentials.store,
            PostgresMcpCatalogStore(
                cloud_composition.dsn, deployment_namespace=cloud_composition.deployment_namespace
            ),
            credentials.protector,
            cloud_composition.deployment_namespace,
        )
    return extension, service, credentials, refresh


def compose_extension_store(
    settings: ZebraAgentSettings,
    stores: ControlPlaneStores | None,
    *,
    cloud_composition: CloudCompositionSettings | None = None,
    extension_store: ExtensionStore | None = None,
) -> ExtensionStore | None:
    """Use explicit cloud injection or admit an enabled, schema-current store."""
    if settings.deployment == "local":
        return None
    if extension_store is not None:
        return extension_store
    if not settings.cloud_extensions_read_enabled:
        return None
    if not isinstance(stores, PostgresControlPlaneStores):
        raise ValueError("cloud extension reads require PostgreSQL control plane stores")
    if (
        cloud_composition is not None
        and cloud_composition.deployment_namespace != stores.deployment_namespace
    ):
        raise ValueError("cloud extension deployment namespace does not match control plane stores")
    dsn = cloud_composition.dsn if cloud_composition is not None else settings.database_url
    require_current_schema(dsn)
    return PostgresExtensionStore(dsn, deployment_namespace=stores.deployment_namespace)


def compose_extension_turn_admission(
    settings: ZebraAgentSettings,
    stores: ControlPlaneStores | None,
    extension_store: ExtensionStore | None,
    *,
    cloud_composition: CloudCompositionSettings | None = None,
) -> CloudExtensionTurnAdmission | None:
    """Keep per-Turn binding independently opt-in and PostgreSQL-only."""
    if not settings.cloud_extension_turn_admission_enabled:
        return None
    if settings.deployment == "local":
        raise ValueError("cloud extension Turn admission is not available locally")
    if not settings.cloud_extensions_read_enabled or extension_store is None:
        raise ValueError("cloud extension Turn admission requires extension reads")
    if not isinstance(stores, PostgresControlPlaneStores):
        raise ValueError("cloud extension Turn admission requires PostgreSQL stores")
    if (
        cloud_composition is not None
        and cloud_composition.deployment_namespace != stores.deployment_namespace
    ):
        raise ValueError("cloud extension deployment namespace does not match control plane stores")
    dsn = cloud_composition.dsn if cloud_composition is not None else settings.database_url
    snapshots = PostgresExtensionSnapshotStore(
        dsn, deployment_namespace=stores.deployment_namespace
    )
    return CloudExtensionTurnAdmission(
        extension_store, snapshots, snapshots,
        mcp_catalogs=(
            PostgresMcpCatalogStore(dsn, deployment_namespace=stores.deployment_namespace)
            if settings.mcp_credentials.worker_enabled else None
        ),
    )


def compose_http_turn_admission(
    settings: ZebraAgentSettings,
    api: ZebraAgentApi,
    extension_store: ExtensionStore | None,
    *,
    cloud_composition: CloudCompositionSettings | None = None,
) -> CloudExtensionTurnAdmission | None:
    """Preserve lazy local/API construction while the feature stays disabled."""
    if (
        settings.mcp_credentials.worker_enabled
        and not settings.cloud_extension_turn_admission_enabled
    ):
        raise ValueError("cloud MCP execution requires extension Turn admission")
    if not settings.cloud_extension_turn_admission_enabled:
        return None
    if settings.deployment == "local" or not settings.cloud_extensions_read_enabled:
        return compose_extension_turn_admission(
            settings, None, extension_store, cloud_composition=cloud_composition
        )
    return compose_extension_turn_admission(
        settings,
        api.stores,
        extension_store,
        cloud_composition=cloud_composition,
    )
