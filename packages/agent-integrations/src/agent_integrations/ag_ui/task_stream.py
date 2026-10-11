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

from collections.abc import Iterator, Sequence

from ag_ui.core import Event
from agent_core.domain.identifiers import SessionId
from agent_core.ports.agent_tasks import TaskEvent

from agent_integrations.ag_ui.contracts import (
    AgUiCursor,
    AgUiProjection,
    AgUiProjectionError,
    AgUiRunIdentity,
)
from agent_integrations.ag_ui.projection import AgUiProjector
from agent_integrations.ag_ui.projection_state import ProjectionState
from agent_integrations.ag_ui.task_run_binding import TaskRunBinding, bind_task_run
from agent_integrations.coverage_public_events import strict_coverage_events


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
        strict_coverage: bool = False,
    ) -> AgUiProjection:
        projected = tuple(
            event for _, event in self.project_task_events(
                task_events, identity, after=after, strict_coverage=strict_coverage
            )
        )
        ordered = tuple(task_events)
        binding = bind_task_run(ordered, identity.run_id)
        return AgUiProjection(
            events=projected,
            next_cursor=_last_cursor(ordered, identity, binding),
            replayed_from=after,
        )

    def validate_task_cursor(
        self,
        task_events: Sequence[TaskEvent],
        identity: AgUiRunIdentity,
        *,
        after: AgUiCursor | None = None,
    ) -> AgUiCursor | None:
        """Inspect canonical positions without materializing the replay backlog."""
        ordered = tuple(task_events)
        binding = _validated_binding(ordered, identity, after)
        if after is not None and after.frame_index is not None:
            # ponytail: retain each Segment across revisits. O(N) cold hydration
            # remains until the bounded-history checkpoint gate closes.
            for entry, frames in self._project_batches(ordered, identity, binding):
                if entry.task_sequence == after.sequence:
                    if after.frame_index >= len(frames):
                        raise AgUiProjectionError("cursor frame is outside its durable Event")
                    break
        return _last_cursor(ordered, identity, binding)

    def project_task_events(
        self,
        task_events: Sequence[TaskEvent],
        identity: AgUiRunIdentity,
        *,
        after: AgUiCursor | None = None,
        strict_coverage: bool = False,
    ) -> Iterator[tuple[AgUiCursor, Event]]:
        """Warm each Segment once, yielding exact intra-Event reconnect positions."""
        ordered = tuple(task_events)
        binding = _validated_binding(ordered, identity, after)
        resume_task_sequence = after.sequence if after is not None else -1

        for entry, frames in self._project_batches(
            ordered, identity, binding, strict_coverage=strict_coverage
        ):
            start = 0
            if entry.task_sequence <= resume_task_sequence:
                if (
                    after is None
                    or entry.task_sequence != after.sequence
                    or after.frame_index is None
                ):
                    continue
                if after.frame_index >= len(frames):
                    raise AgUiProjectionError("cursor frame is outside its durable Event")
                start = after.frame_index + 1
            for index in range(start, len(frames)):
                yield (
                    AgUiCursor(
                        thread_id=identity.thread_id,
                        run_id=identity.run_id,
                        sequence=entry.task_sequence,
                        event_id=str(entry.event.event_id),
                        frame_index=index,
                    ),
                    frames[index],
                )

    def _project_batches(
        self, ordered: tuple[TaskEvent, ...], identity: AgUiRunIdentity, binding: TaskRunBinding,
        *, strict_coverage: bool = False,
    ) -> Iterator[tuple[TaskEvent, tuple[Event, ...]]]:
        states: dict[SessionId, ProjectionState] = {}
        strict = strict_coverage or strict_coverage_events(entry.event for entry in ordered)
        for segment_slice in _contiguous_segments(ordered):
            eligible = [entry for entry in segment_slice if binding.includes(entry)]
            if not eligible:
                continue
            segment_slice = tuple(
                e for e in segment_slice if (e.task_sequence <= eligible[-1].task_sequence)
            )
            segment_identity = AgUiRunIdentity(
                session_id=segment_slice[0].segment_id,
                thread_id=identity.thread_id,
                run_id=identity.run_id,
            )
            state = states.setdefault(segment_identity.session_id, ProjectionState())
            events = [entry.event for entry in segment_slice]
            projected = (
                self._projector.project_events(
                    events, segment_identity, state=state, strict_coverage=True
                )
                if strict else self._projector.project_events(events, segment_identity, state=state)
            )
            for entry, (_, frames) in zip(segment_slice, projected, strict=True):
                if not binding.includes(entry):
                    continue
                yield entry, frames


def _validated_binding(
    ordered: tuple[TaskEvent, ...], identity: AgUiRunIdentity, after: AgUiCursor | None
) -> TaskRunBinding:
    _validate_task_ordering(ordered)
    if any(str(entry.task_id) != identity.thread_id for entry in ordered):
        raise AgUiProjectionError("events do not belong to the requested Task")
    binding = bind_task_run(ordered, identity.run_id)
    if after is not None:
        if after.thread_id != identity.thread_id or after.run_id != identity.run_id:
            raise AgUiProjectionError("cursor does not match the requested Task/run")
        anchor = next((e for e in ordered if e.task_sequence == after.sequence), None)
        if anchor is None or str(anchor.event.event_id) != after.event_id:
            raise AgUiProjectionError("cursor does not identify a canonical Task event")
        if not binding.legacy and (
            binding.anchor is None
            or after.sequence < binding.start - 1
            or (binding.stop is not None and after.sequence >= binding.stop)
        ):
            raise AgUiProjectionError("cursor is outside the requested run")
        if after.frame_index is not None and not binding.includes(anchor):
            raise AgUiProjectionError("cursor frame is outside the requested run")
    return binding


def _last_cursor(
    ordered: tuple[TaskEvent, ...], identity: AgUiRunIdentity, binding: TaskRunBinding
) -> AgUiCursor | None:
    last = next((entry for entry in reversed(ordered) if binding.includes(entry)), None)
    return (
        None
        if last is None
        else AgUiCursor(
            thread_id=identity.thread_id,
            run_id=identity.run_id,
            sequence=last.task_sequence,
            event_id=str(last.event.event_id),
        )
    )


def _validate_task_ordering(events: tuple[TaskEvent, ...]) -> None:
    previous = -1
    segment_sequences: dict[SessionId, int] = {}
    seen: set[str] = set()
    for entry in events:
        if (
            entry.segment_id != entry.event.session_id
            or entry.segment_sequence != entry.event.sequence
        ):
            raise AgUiProjectionError("Task index does not match its canonical Event")
        if entry.task_sequence != previous + 1:
            raise AgUiProjectionError("task events must have contiguous task_sequence")
        if entry.segment_sequence <= segment_sequences.get(entry.segment_id, -1):
            raise AgUiProjectionError("durable events must have unique increasing sequences")
        event_id = str(entry.event.event_id)
        if event_id in seen:
            raise AgUiProjectionError("task events must be unique per Task")
        previous = entry.task_sequence
        segment_sequences[entry.segment_id] = entry.segment_sequence
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
