"""Runtime helpers for durable client effects in the worker loop.

The exposure gate keeps the ADR-CLIENT-01 intersection: client actions
reach the model only through an allowed binding held by the active
controller of THIS run; subagents and orchestrators never receive the
channel.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.client_run_bindings import ClientRunBinding
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.platform_control_plane import AgentPlatformControlPlane

from zebra_agent_worker.client_tool_gateway import (
    ClientToolGateway,
    compose_client_tool_gateway,
)


class ClientEffectRuntimeError(ValueError):
    pass


def build_client_gateway_for_task(
    *,
    platform: AgentPlatformControlPlane | None,
    task_id: SessionId,
    run_id: str,
    client_session_resolver: Any = None,
) -> ClientToolGateway | None:
    """Compose the schedule-only channel when a controller binding exists."""

    if platform is None or platform.client_sessions is None:
        return None
    if client_session_resolver is None:
        return None
    session_id = client_session_resolver(task_id)
    if session_id is None:
        return None  # no active controller binding for this run
    binding = platform.client_sessions.get_run_binding(
        TaskId(task_id), run_id, session_id
    )
    if binding is None or not binding.allowed_actions:
        return None
    fence = _controller_fence(platform, binding, session_id)
    if fence is None:
        return None
    snapshot = platform.client_sessions.get_mounted_snapshot(session_id)
    ui_revision = snapshot.ui_revision if snapshot is not None else 0
    return compose_client_tool_gateway(
        platform=platform,
        binding=binding,
        fence=fence,
        session_id=task_id,
        ui_revision=ui_revision,
    )


def _controller_fence(
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
    from agent_core.domain.client_sessions import ClientControlFence

    # The worker never holds the raw token; it pins effects to the lease's
    # persisted fence hash via a derived schedule fence.
    return ClientControlFence(token=f"worker-schedule:{lease.fence_hash}")
