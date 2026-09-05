"""Canonical Task/run windows shared by replay and stream termination."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_core.domain.events import EventType
from agent_core.ports.agent_tasks import TaskEvent

from agent_integrations.ag_ui.contracts import AgUiProjectionError

EXECUTABLE_KINDS = frozenset({"run", "resume", "message"})


def command_run_id(entry: TaskEvent) -> str | None:
    payload = entry.event.payload.get("payload")
    value = payload.get("run_id") if isinstance(payload, Mapping) else None
    return value if isinstance(value, str) else None


@dataclass(frozen=True, slots=True)
class TaskRunBinding:
    anchor: TaskEvent | None
    start: int
    stop: int | None
    segments: frozenset[str]
    legacy: bool = False
    control_only: bool = False

    def includes(self, entry: TaskEvent) -> bool:
        return (
            not self.control_only
            and (self.legacy or self.anchor is not None)
            and self.start <= entry.task_sequence
            and (self.stop is None or entry.task_sequence < self.stop)
            and (self.legacy or str(entry.segment_id) in self.segments)
        )


def bind_task_run(events: Sequence[TaskEvent], run_id: str) -> TaskRunBinding:
    commands = [e for e in events if e.event.event_type is EventType.SESSION_COMMAND_ACCEPTED]
    if not commands:
        # ponytail: command-less local replay retains the pre-command protocol.
        return TaskRunBinding(None, 0, None, frozenset(), legacy=True)
    matches = [e for e in commands if command_run_id(e) == run_id]
    executable = [e for e in matches if e.event.payload.get("kind") in EXECUTABLE_KINDS]
    anchors = executable or matches
    if len(anchors) > 1:
        raise AgUiProjectionError("ambiguous canonical Task/run command")
    if not anchors:
        return TaskRunBinding(None, 0, None, frozenset())
    anchor = anchors[0]
    stop = next(
        (
            e.task_sequence
            for e in commands
            if (
                e.task_sequence > anchor.task_sequence
                and e.event.payload.get("kind") in EXECUTABLE_KINDS
                and command_run_id(e) != run_id
            )
        ),
        None,
    )
    segments = {str(anchor.segment_id)}
    committed: dict[tuple[str, str], str] = {}
    for entry in events:
        if entry.task_sequence < anchor.task_sequence:
            continue
        if stop is not None and entry.task_sequence >= stop:
            break
        payload = entry.event.payload
        if entry.event.event_type is EventType.SESSION_HANDOFF_COMMITTED:
            if str(entry.segment_id) in segments:
                committed[(str(entry.segment_id), str(payload.get("handoff_id")))] = str(
                    payload.get("target_session_id")
                )
        elif entry.event.event_type is EventType.SESSION_HANDOFF_RECEIVED:
            key = (str(payload.get("parent_session_id")), str(payload.get("handoff_id")))
            if committed.get(key) == str(entry.segment_id):
                segments.add(str(entry.segment_id))
    return TaskRunBinding(
        anchor, anchor.task_sequence, stop, frozenset(segments), control_only=not executable
    )
