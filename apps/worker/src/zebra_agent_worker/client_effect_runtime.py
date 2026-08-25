"""Runtime helpers for durable client effects in the worker loop.

The exposure gate keeps the ADR-CLIENT-01 intersection: client actions
reach the model only through an allowed binding held by the active
controller of THIS run; subagents and orchestrators never receive the
channel.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent_core.domain.client_run_bindings import ClientRunBinding
from agent_core.domain.identifiers import SessionId
from agent_core.ports.platform_control_plane import AgentPlatformControlPlane

from zebra_agent_worker.client_tool_gateway import (
    ClientToolGateway,
    compose_client_tool_gateway,
)


class ClientEffectRuntimeError(ValueError):
    pass


def compose_client_runtime(
    dsn: str | None, *, deployment_namespace: str, enabled: bool
) -> Callable[[SessionId], ClientToolGateway | None] | None:
    if not enabled:
        return None
    if dsn is None or not dsn.strip():
        raise ClientEffectRuntimeError("client integration requires the cloud PostgreSQL DSN")
    from zebra_agent_worker.platform_composition import (
        compose_worker_platform_control_plane,
    )

    platform = compose_worker_platform_control_plane(
        dsn,
        deployment_namespace=deployment_namespace,
        client_integration_enabled=True,
    )
    return lambda task_id: build_client_gateway_for_task(platform=platform, task_id=task_id)


def build_client_gateway_for_task(
    *,
    platform: AgentPlatformControlPlane | None,
    task_id: SessionId,
) -> ClientToolGateway | None:
    """Compose the schedule-only channel when a controller binding exists."""

    if platform is None or platform.client_sessions is None:
        return None
    binding = platform.client_sessions.get_active_run_binding(task_id)
    if binding is None or not binding.allowed_actions:
        return None
    session_id = binding.client_session_id
    fence_hash = _controller_fence_hash(platform, binding, session_id)
    if fence_hash is None:
        return None
    snapshot = platform.client_sessions.get_mounted_snapshot(session_id)
    capabilities = platform.frontend_capabilities
    if snapshot is None or capabilities is None:
        return None
    profile = capabilities.get_profile(snapshot.frontend_app_id, snapshot.profile_revision)
    if profile is None or profile.profile_digest != snapshot.profile_digest:
        return None
    action_contracts = {
        action.name: action for action in profile.actions if action.name in binding.allowed_actions
    }
    if set(action_contracts) != set(binding.allowed_actions):
        return None
    return compose_client_tool_gateway(
        platform=platform,
        binding=binding,
        fence_hash=fence_hash,
        session_id=task_id,
        ui_revision=snapshot.ui_revision,
        action_contracts=action_contracts,
    )


def _controller_fence_hash(
    platform: AgentPlatformControlPlane, binding: ClientRunBinding, session_id: Any
) -> Any | None:
    leases = platform.client_control_leases
    if leases is None:
        return None
    lease = leases.get_active(binding.binding_id)
    if lease is None or lease.is_expired():
        return None
    if lease.client_session_id != session_id:
        return None
    # The worker never reconstructs the raw bearer; effects pin the exact
    # persisted lease hash so the controller can prove possession later.
    return lease.fence_hash
