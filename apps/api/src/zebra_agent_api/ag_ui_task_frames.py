"""Exact source cursors without replaying every known-private strict prefix."""

from ag_ui.encoder import EventEncoder
from agent_core.ports.agent_tasks import TaskEvent
from agent_integrations.ag_ui import AgUiCursor, AgUiRunIdentity
from agent_integrations.ag_ui.task_run_binding import bind_task_run
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_integrations.coverage_public_events import (
    coverage_projection_event,
    strict_coverage_events,
)


def project_new_task_events(
    events: list[TaskEvent] | tuple[TaskEvent, ...],
    identity: AgUiRunIdentity,
    after: AgUiCursor | None,
) -> list[tuple[AgUiCursor, str]]:
    start_sequence = after.sequence if after is not None else -1
    previous = after
    encoder = EventEncoder()
    projector = AgUiTaskProjector()
    projected: list[tuple[AgUiCursor, str]] = []
    binding = bind_task_run(events, identity.run_id)
    strict = strict_coverage_events(entry.event for entry in events)
    slices = {}
    if strict:
        # Validate even hidden tails/cursors before skipping any private prefix.
        projector.project_task(events, identity, after=after)
        slice_start = 0
        for index, entry in enumerate(events):
            if index == 0 or entry.segment_id != events[index - 1].segment_id:
                slice_start = index
            slices[entry.task_sequence] = slice_start
    for index, entry in enumerate(events):
        if entry.task_sequence <= start_sequence or not binding.includes(entry):
            continue
        if (
            strict and previous is not None
            and slices[previous.sequence] == slices[entry.task_sequence]
            and coverage_projection_event(entry.event, strict=True) is None
        ):
            continue
        # ponytail: O(N*P) replay for P visible events/Segment starts remains;
        # a stateful tagged projector is the upgrade, not weaker cursor checks.
        projection = projector.project_task(
            events[: index + 1], identity, after=previous, strict_coverage=strict,
        )
        next_cursor = projection.next_cursor
        if next_cursor is None:
            continue
        for agui_event in projection.events:
            projected.append((next_cursor, f"id: {next_cursor.encode()}\n"
                              f"{encoder.encode(agui_event)}"))
        previous = next_cursor
    return projected
