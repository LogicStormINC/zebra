"""Trusted worker context to a database-bound runtime instance collaborator."""

from collections.abc import Callable

from agent_core.application.execution_authority_replay import latest_authority_snapshot
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import SessionEvent
from agent_core.domain.leases import WorkerLease
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_runtime.runtime_instance_lifecycle import RuntimeInstanceLifecycle

InstanceFactory = Callable[
    [WorkerLease, OpaqueAuthorityScope, str | None, str], RuntimeInstanceLifecycle
]
BoundInstanceFactory = Callable[[str], RuntimeInstanceLifecycle]


def bind_instance_factory(
    factory: InstanceFactory | None,
    lease: WorkerLease,
    events: list[SessionEvent],
    binding: TaskBindingSnapshot | None,
) -> BoundInstanceFactory | None:
    if factory is None:
        return None
    authority = latest_authority_snapshot(events)
    if authority is None:
        raise ValueError("cloud runtime requires canonical execution authority")
    context = None if binding is None else binding.host_capability.host_context
    workspace_ref = None if context is None else context.workspace_ref
    return lambda engine: factory(lease, authority.scope, workspace_ref, engine)
