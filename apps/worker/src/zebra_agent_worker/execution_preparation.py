"""Advance durable setup without releasing its lease or spending retry attempts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from agent_core.domain.events import SessionEvent
from agent_core.domain.leases import WorkerLease
from agent_core.ports.event_store import EventStorePort
from agent_core.ports.worker_preparation import PreparationAdvanced

if TYPE_CHECKING:
    from zebra_agent_worker.claims import ClaimedSession
    from zebra_agent_worker.execution_recovery import RecoveredExecutionInputs


def finish_preparation[T](operation: Callable[[], T], ownership_check: Callable[[], None]) -> T:
    # ponytail: only committed, strictly advancing slices are retried inline.
    # Dependency failures escape normally; no timer or guessed progress retries.
    frontiers: dict[str, tuple[int, int]] = {}
    for _ in range(4096):
        ownership_check()
        try:
            return operation()
        except PreparationAdvanced as progress:
            previous = frontiers.get(progress.checkpoint_key)
            if previous is not None and (
                progress.through_sequence <= previous[0] or progress.highwater < previous[1]
            ):
                raise ValueError(
                    "Worker preparation did not advance its durable frontier"
                ) from progress
            if len(frontiers) >= 16 and progress.checkpoint_key not in frontiers:
                raise ValueError(
                    "Worker preparation changed checkpoint identity too often"
                ) from progress
            frontiers[progress.checkpoint_key] = (progress.through_sequence, progress.highwater)
    raise ValueError("Worker preparation exceeded its bounded slice budget")


def prepare_execution_inputs(
    service: Any,
    claimed: ClaimedSession,
    started_at: datetime,
    ownership_check: Callable[[], None],
    recover: Callable[..., RecoveredExecutionInputs],
) -> RecoveredExecutionInputs:
    """Keep the pre-effect recovery boundary separate from actual execution."""
    return finish_preparation(
        lambda: recover(
            claimed=claimed,
            session_id=claimed.lease.session_id,
            started_at=started_at,
            cloud_deployment=service._settings.deployment == "cloud",
            cloud_provider_continuation_factory=service._cloud_provider_continuation_factory,
            provider_continuation_store=service._provider_continuation_store,
            control_service=service._control_service,
            recovery_service=service._recovery_service,
            event_store=service._event_store,
            context_lifecycle_store=service._context_lifecycle_store,
            handoff_gate=service._handoff_gate,
            artifact_payload_reader=service._artifact_payload_reader,
            workspace_resolver=service._workspace_resolver,
            execution_input_store=service._execution_input_store,
            tasks=service._task_index_store,
            namespace=service._execution_namespace,
            ownership_check=ownership_check,
        ),
        ownership_check,
    )


def execution_event_view(
    events: EventStorePort,
    reader: Callable[[WorkerLease], list[SessionEvent]] | None,
    lease: WorkerLease,
    ownership_check: Callable[[], None],
) -> EventStorePort:
    if reader is None:
        return events
    from zebra_agent_worker.execution_input_preparation import ExecutionInputEventView

    return ExecutionInputEventView(
        events,
        lambda current: finish_preparation(lambda: reader(current), ownership_check),
        lease,
    )
