"""Opt-in MCP startup using the existing PostgreSQL Worker authority bundle."""

from agent_core.application import current_turn
from agent_core.application.execution_authority_replay import latest_authority_snapshot
from agent_core.domain.identifiers import SessionId
from agent_core.ports.event_store import EventStorePort
from agent_runtime.mcp_catalog_refresh import McpCatalogRefresh
from agent_security.mcp_credential_protection import mounted_mcp_protector
from agent_security.mcp_credential_release import McpCredentialRelease
from agent_security.mcp_execution_authority import McpWorkerAuthority
from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
from agent_storage.postgres.mcp_credentials import PostgresMcpCredentialStore
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.cloud_composition import CloudWorkerComposition
from zebra_agent_worker.worker_mcp_catalog import WorkerMcpSource


def load_worker_mcp_authority(
    events: EventStorePort, session_id: SessionId, turn_id: str,
) -> McpWorkerAuthority:
    """Replay durable attempt revalidation; never resolve a new or longer Grant."""
    # ponytail: O(session events) per frame; a scoped authority projection is
    # the upgrade path if long-session profiling makes replay a bottleneck.
    history = events.list_for_session(session_id)
    turn = current_turn(history)
    if turn is None or turn.turn_id != turn_id:
        raise ValueError("MCP operation is not bound to the current Turn")
    snapshot = latest_authority_snapshot(history)
    if snapshot is None:
        raise ValueError("MCP Worker has no durable execution authority")
    authority = McpWorkerAuthority(str(session_id), snapshot)
    authority.require_live()
    return authority


def compose_worker_mcp(
    settings: ZebraAgentSettings, cloud: CloudWorkerComposition | None,
) -> WorkerMcpSource | None:
    config = settings.mcp_credentials
    if not config.worker_enabled:
        return None
    if (
        settings.deployment != "cloud"
        or settings.storage_authority != "postgresql"
        or not settings.cloud_extension_worker_enabled
        or cloud is None
        or not cloud.dsn
        or cloud.extension_snapshots is None
    ):
        raise ValueError("cloud MCP Worker requires PostgreSQL extension recovery composition")
    protector = mounted_mcp_protector(config.secret_root, config.key_handle, config.key_version)
    connections = PostgresMcpCredentialStore(
        cloud.dsn, deployment_namespace=cloud.deployment_namespace,
    )
    snapshots = cloud.extension_snapshots
    return WorkerMcpSource(
        catalogs=PostgresMcpCatalogStore(
            cloud.dsn, deployment_namespace=cloud.deployment_namespace,
        ),
        connections=connections,
        release=McpCredentialRelease(
            connections, snapshots, snapshots, protector, cloud.deployment_namespace,
        ),
        leases=cloud.stores.leases,
        execution_authority=lambda session, turn: load_worker_mcp_authority(
            cloud.stores.events, session, turn,
        ),
        refresh=McpCatalogRefresh(
            connections, PostgresMcpCatalogStore(
                cloud.dsn, deployment_namespace=cloud.deployment_namespace,
            ), protector, cloud.deployment_namespace,
        ),
    )
