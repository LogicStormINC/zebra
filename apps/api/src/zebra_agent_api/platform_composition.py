"""API-side platform control-plane composition (ADR-CLIENT-01).

Re-exports the storage bundle so the API composes the exact same
platform contract as the worker. Client stores appear only when the
default-off client integration flag is enabled; no business host name
is referenced here.
"""

from __future__ import annotations

from agent_core.ports.platform_control_plane import AgentPlatformControlPlane
from agent_storage.postgres_platform_composition import (
    postgres_agent_platform_control_plane,
)

__all__ = [
    "AgentPlatformControlPlane",
    "compose_api_platform_control_plane",
]


def compose_api_platform_control_plane(
    dsn: str,
    *,
    deployment_namespace: str,
    client_integration_enabled: bool = False,
) -> AgentPlatformControlPlane:
    if not dsn.strip():
        raise ValueError("cloud API startup requires a PostgreSQL DSN")
    if not deployment_namespace.strip():
        raise ValueError("cloud API startup requires a deployment namespace")
    bundle = postgres_agent_platform_control_plane(
        dsn,
        deployment_namespace=deployment_namespace,
        client_integration_enabled=client_integration_enabled,
    )
    if client_integration_enabled:
        bundle.require_client_stores()
    return bundle
