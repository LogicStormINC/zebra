"""Repair only a checkpoint-owned source gap, using indexed point pages and fenced append."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from agent_core.contracts.public_output import PublicOutputPayload
from agent_core.domain.events import EventType
from agent_core.harness.commentary_progress import accept_commentary
from agent_core.harness.model_commentary import commentary_outputs
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports.task_projection_checkpoints import CheckpointConflict

if TYPE_CHECKING:
    from zebra_agent_worker.progress_recovery import WorkerProgressRecovery


def repair_commentary(
    recovery: "WorkerProgressRecovery", sink: Callable[[HarnessEventDraft], None]
) -> None:
    source = recovery.catch_up()
    pending = recovery.head.state.pending_commentary
    if pending is None or recovery.head.state.terminal:
        return  # Cancellation never grants authority to finish an abandoned publication.
    recovery.ownership_check()
    if source is None:
        page = recovery.tasks.read_event_page(
            recovery.head.scope.task_id,
            pending.source_sequence - 1,
            limit=1,
            max_bytes=1_048_576,
            through_sequence=pending.source_sequence,
        )
        if len(page.events) != 1:
            raise CheckpointConflict("pending commentary source is not the exact canonical point")
        source = page.events[0]
    if (
        source.task_sequence != pending.source_sequence
        or source.task_id != recovery.head.scope.task_id
        or source.event.event_type is not EventType.MODEL_RESPONSE_RECEIVED
    ):
        raise CheckpointConflict("pending commentary source is not the exact canonical point")
    drafts = commentary_outputs(source.event.payload)
    if tuple(str(d.payload["output_id"]) for d in drafts) != tuple(pending.output_ids):
        raise CheckpointConflict("pending commentary source identity disagrees")
    # At most eight chunks; outer publication scope supplies ONE cumulative deadline.
    while (pending := recovery.head.state.pending_commentary) is not None:
        if recovery.head.state.terminal:
            return
        recovery.ownership_check()
        accept_commentary(
            PublicOutputPayload.model_validate(drafts[pending.next_index].payload),
            recovery.head.state.model_dump(),
        )
        sink(drafts[pending.next_index])  # Existing recorder atomically validates the DB fence.
        recovery.catch_up()  # Unknown commit/checkpoint failure is retried via canonical index.
        remaining = recovery.head.state.pending_commentary
        if remaining is not None and remaining.next_index <= pending.next_index:
            raise CheckpointConflict("commentary repair did not durably advance its frontier")
