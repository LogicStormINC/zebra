"""Task-level AG-UI projection: one continuous cursor across Segments.

AL-QUERY-API-V1-01 (ADR-017 / plan section 8.3): the Host-visible stream is
the Task, not the active Segment. Rollover must not break event continuity.
This adapter groups ``TaskEvent`` rows into contiguous Segments, reuses the
per-segment ``AgUiProjector`` unchanged, and renumbers every emitted cursor
into the Task's monotonic ``task_sequence`` space. Each newly entered Segment
emits its own ``RunStarted`` (a run continuation inside the same thread),
which is the correct AG-UI semantics for a rollover.
"""

from __future__ import annotations

from collections.abc import Sequence

from ag_ui.core import Event
from agent_core.ports.agent_tasks import TaskEvent

from agent_integrations.ag_ui.contracts import (
    AgUiCursor,
    AgUiProjection,
    AgUiProjectionError,
    AgUiRunIdentity,
)
from agent_integrations.ag_ui.projection import AgUiProjector


class AgUiTaskProjector:
    """Project cross-Segment Task events with Task-scoped cursors."""

    def __init__(self, projector: AgUiProjector | None = None) -> None:
        self._projector = projector or AgUiProjector()

    def project_task(
        self,
        task_events: Sequence[TaskEvent],
        identity: AgUiRunIdentity,
        *,
        after: AgUiCursor | None = None,
    ) -> AgUiProjection:
        ordered = tuple(task_events)
        _validate_task_ordering(ordered)
        if after is not None and (
            after.thread_id != identity.thread_id or after.run_id != identity.run_id
        ):
            raise AgUiProjectionError("cursor does not match the requested Task/run")
        resume_task_sequence = after.sequence if after is not None else -1

        projected_events: list[Event] = []
        for segment_slice in _contiguous_segments(ordered):
            resume_inside = [
                entry for entry in segment_slice if entry.task_sequence <= resume_task_sequence
            ]
            if len(resume_inside) == len(segment_slice):
                continue
            segment_after: AgUiCursor | None = None
            if resume_inside:
                anchor = resume_inside[-1]
                segment_after = AgUiCursor(
                    thread_id=identity.thread_id,
                    run_id=identity.run_id,
                    sequence=anchor.segment_sequence,
                    event_id=str(anchor.event.event_id),
                )
            segment_identity = AgUiRunIdentity(
                session_id=segment_slice[0].segment_id,
                thread_id=identity.thread_id,
                run_id=identity.run_id,
            )
            projection = self._projector.project(
                [entry.event for entry in segment_slice],
                segment_identity,
                after=segment_after,
            )
            projected_events.extend(projection.events)

        next_cursor: AgUiCursor | None = None
        if ordered:
            last = ordered[-1]
            next_cursor = AgUiCursor(
                thread_id=identity.thread_id,
                run_id=identity.run_id,
                sequence=last.task_sequence,
                event_id=str(last.event.event_id),
            )
        return AgUiProjection(
            events=tuple(projected_events),
            next_cursor=next_cursor,
            replayed_from=after,
        )


def _validate_task_ordering(events: tuple[TaskEvent, ...]) -> None:
    previous = -1
    seen: set[str] = set()
    for entry in events:
        if entry.task_sequence <= previous:
            raise AgUiProjectionError("task events must have increasing task_sequence")
        event_id = str(entry.event.event_id)
        if event_id in seen:
            raise AgUiProjectionError("task events must be unique per Task")
        previous = entry.task_sequence
        seen.add(event_id)


def _contiguous_segments(events: tuple[TaskEvent, ...]) -> list[tuple[TaskEvent, ...]]:
    segments: list[tuple[TaskEvent, ...]] = []
    current: list[TaskEvent] = []
    for entry in events:
        if current and entry.segment_id != current[-1].segment_id:
            segments.append(tuple(current))
            current = []
        current.append(entry)
    if current:
        segments.append(tuple(current))
    return segments
