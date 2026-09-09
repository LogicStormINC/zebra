"""Compose pinned MCP transport from trusted recovered Worker coordinates."""

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from agent_core.domain.extension_snapshots import McpSnapshotEntry
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.mcp_catalog import McpToolCatalog
from agent_core.ports.lease_store import LeaseStorePort
from agent_core.ports.mcp_catalog import McpCatalogStore
from agent_core.ports.mcp_credentials import McpCredentialManagementStore
from agent_runtime.cloud_mcp_transport import CloudMcpTransport
from agent_runtime.mcp_catalog_refresh import McpCatalogRefresh
from agent_runtime.mcp_execution_authorization import McpExecutionCredentialResolver
from agent_runtime.mcp_http_authorization import McpHttpBearerCredential
from agent_security.mcp_credential_release import McpCredentialRelease
from agent_security.mcp_execution_authority import McpWorkerAuthority
from agent_tools import McpProxyRequest

from zebra_agent_worker.extension_recovery import RecoveredTurnExtension


@dataclass(frozen=True)
class WorkerMcpSource:
    catalogs: McpCatalogStore
    connections: McpCredentialManagementStore
    release: McpCredentialRelease
    leases: LeaseStorePort
    execution_authority: Callable[[SessionId, str], McpWorkerAuthority]
    refresh: McpCatalogRefresh | None = None


def prepare_worker_mcp(
    extension: RecoveredTurnExtension | None,
    *,
    source: WorkerMcpSource | None,
    session_id: SessionId,
    fence: LeaseFence,
) -> CloudMcpTransport | None:
    if extension is None or not extension.snapshot.mcp:
        return None
    if source is None:
        raise ValueError("MCP Worker authority is not configured")
    snapshot = extension.snapshot
    if snapshot.scope != extension.scope or snapshot.session_id != str(session_id):
        raise ValueError("MCP Worker recovery identity mismatch")

    async def load() -> tuple[McpToolCatalog, ...]:
        return tuple(
            await asyncio.gather(
                *(
                    source.catalogs.get(
                        scope=extension.scope,
                        connection_id=entry.connection.connection_id,
                        config_revision=entry.connection.revision,
                        expected_digest=entry.catalog_digest,
                    )
                    for entry in snapshot.mcp
                )
            )
        )

    def authorize(
        entry: McpSnapshotEntry,
        operation: McpProxyRequest,
        endpoint: str,
        frame: Mapping[str, object],
    ) -> McpHttpBearerCredential | None:
        resolver = McpExecutionCredentialResolver(
            release=source.release,
            leases=source.leases,
            fresh_authority=lambda: source.execution_authority(session_id, snapshot.turn_id),
            session_id=session_id,
            turn_id=snapshot.turn_id,
            snapshot_digest=snapshot.digest,
            fence=fence,
            connection_id=entry.connection.connection_id,
            endpoint=entry.connection.endpoint,
            method="tools/call",
            params_json=json.dumps(
                {
                    "name": operation.target.tool_name,
                    "arguments": operation.arguments,
                },
                allow_nan=False,
            ),
            connections=source.connections,
        )
        if entry.connection.auth_mode.value == "none":
            resolver.authorize_anonymous(endpoint, frame)
            return None
        return resolver(endpoint, frame)

    return CloudMcpTransport(snapshot, asyncio.run(load()), authorize=authorize)
