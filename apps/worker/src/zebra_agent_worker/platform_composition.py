"""Worker-side platform control-plane composition (ADR-CLIENT-01).

Re-exports the storage bundle so the worker composes the exact same
platform contract as the API. Cloud startup fails closed when client
integration is enabled but stores are missing; the worker never
connects to a browser through this bundle.
"""

from __future__ import annotations

from agent_core.ports.platform_control_plane import AgentPlatformControlPlane
from agent_storage.postgres_platform_composition import (
    postgres_agent_platform_control_plane,
)

__all__ = [
    "AgentPlatformControlPlane",
    "compose_worker_platform_control_plane",
]


def compose_worker_platform_control_plane(
    dsn: str,
    *,
    deployment_namespace: str,
    client_integration_enabled: bool = False,
) -> AgentPlatformControlPlane:
    if not dsn.strip():
        raise ValueError("cloud worker startup requires a PostgreSQL DSN")
    if not deployment_namespace.strip():
        raise ValueError("cloud worker startup requires a deployment namespace")
    bundle = postgres_agent_platform_control_plane(
        dsn,
        deployment_namespace=deployment_namespace,
        client_integration_enabled=client_integration_enabled,
    )
    if client_integration_enabled:
        bundle.require_client_stores()
    return bundle
