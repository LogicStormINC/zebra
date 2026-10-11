"""Independent certificate budget proof; never an incremental commit path."""
from datetime import datetime
from typing import Any

from agent_core.domain.coverage_persistence import CoverageRunBinding

from agent_storage.postgres.coverage_model_checkpoint import check_checkpoint_retention


def certify_model_budget(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    *,
    at: datetime,
    artifacts: Any,
    retention_deadlines: list[datetime] | None = None,
) -> None:
    from agent_storage.postgres.coverage_model_source import replay_model, task_policy

    # ponytail: each certificate gate replays O(n) source receipts and rereads n
    # bounded objects. A retention-pinned immutable proof root is the upgrade path;
    # row hashes alone cannot prove that original object bytes remain available.
    deadlines = [] if retention_deadlines is None else retention_deadlines
    state, _ = replay_model(
        connection, deployment, binding, artifacts=artifacts, retention_deadlines=deadlines
    )
    if state is None:
        if task_policy(connection, deployment, binding) is not None:
            raise ValueError("strict certification requires an initialized model ledger")
        return
    if state.unresolved or not state.policy.started_at <= at < state.policy.deadline:
        raise ValueError("strict certification has unresolved usage or expired execution deadline")
    check_checkpoint_retention(connection, deadlines)
