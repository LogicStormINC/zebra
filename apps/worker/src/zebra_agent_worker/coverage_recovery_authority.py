"""Fresh recovery authority, optionally sharing the current wake's lineage proof."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from agent_core.domain.leases import LeaseFence
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports.effect_dispatch import effect_input
from agent_storage.postgres.coverage_authority import PostgresCoverageAuthority
from agent_storage.postgres.task_admission import load_session_task_binding


def prepare_recovery_authority(
    runtime: Any, service: Any, session: Any, pinned: TaskBindingSnapshot,
    fence: LeaseFence, policy: Any, *, issued: bool,
    execution_authority: PostgresCoverageAuthority | None = None,
) -> Callable[[], None]:
    database = runtime.metadata._database
    if execution_authority is not None and (
        type(execution_authority) is not PostgresCoverageAuthority
        or execution_authority.database._dsn != database._dsn
        or execution_authority.database.deployment_namespace != database.deployment_namespace
        or execution_authority.session != session
        or execution_authority.binding != pinned
        or execution_authority.fence != fence
    ):
        raise ValueError("recovery execution authority belongs to another wake or scope")
    context = execution_authority or PostgresCoverageAuthority.prepare(
        database, session, pinned, fence,
        lambda identifier: load_session_task_binding(
            runtime.dsn, deployment_namespace=database.deployment_namespace,
            session_id=identifier,
        ),
    )
    host = pinned.host_capability.host_context
    if host is None or host.expires_at is None:
        raise ValueError("strict command proof requires retained source authority")
    limit = host.expires_at if issued else min(policy.deadline, host.expires_at)

    def current() -> None:
        if context is not None:
            context.check_lineage(deadline=limit)
        fresh = pinned if context is not None else service._task_binding_loader(session)
        if (
            not isinstance(fresh, TaskBindingSnapshot)
            or TaskBindingSnapshot.model_validate(effect_input(fresh), strict=True) != pinned
        ):
            raise ValueError("strict command proof Task binding changed")
        if not policy.started_at <= datetime.now(UTC) < limit:
            raise ValueError("strict command proof original authority expired")

    return current
