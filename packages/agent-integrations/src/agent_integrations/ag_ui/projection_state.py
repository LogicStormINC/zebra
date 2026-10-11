"""Per-segment transient state for deterministic incremental AG-UI projection."""

from dataclasses import dataclass, field
from typing import Any

from ag_ui.core import Interrupt
from agent_core.ports.task_projection_checkpoints import (
    ProjectionCell,
    ProjectionCellKey,
    SegmentCheckpoint,
)

from agent_integrations.ag_ui.contracts import AgUiProjectionError, AgUiRunIdentity


@dataclass(slots=True)
class ProjectionState:
    binding: tuple[str, str, str, str | None] | None = None
    last_sequence: int = -1
    started: bool = False
    text_messages: dict[str, str] = field(default_factory=dict)
    text_ended: set[str] = field(default_factory=set)
    tool_calls: set[str] = field(default_factory=set)
    open_interrupts: dict[str, Interrupt] = field(default_factory=dict)
    # Membership only: checkpoints never retain an Interrupt's message/schema.
    checkpoint_interrupt_ids: set[str] = field(default_factory=set)
    # A trailing Segment terminal must not finish an already completed Turn twice.
    turn_finished: bool = False
    coverage_runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    strict_coverage: bool = False

    def bind(self, identity: AgUiRunIdentity) -> None:
        binding = (
            str(identity.session_id),
            identity.thread_id,
            identity.run_id,
            identity.parent_run_id,
        )
        if self.binding is not None and self.binding != binding:
            raise AgUiProjectionError("projection state belongs to another Session/run")
        self.binding = binding

    @classmethod
    def from_checkpoint(
        cls,
        scalar: SegmentCheckpoint,
        cells: tuple[ProjectionCell, ...],
        identity: AgUiRunIdentity,
    ) -> "ProjectionState":
        if scalar.segment_id != identity.session_id:
            raise AgUiProjectionError("checkpoint belongs to another Segment")
        state = cls(
            last_sequence=scalar.segment_sequence,
            started=scalar.started,
            turn_finished=scalar.turn_finished,
        )
        state.bind(identity)
        for cell in cells:
            if cell.key.segment_id != scalar.segment_id:
                raise AgUiProjectionError("checkpoint cell belongs to another Segment")
            if cell.value is None:
                continue
            key = cell.key.key
            if cell.key.kind == "text_message":
                state.text_messages[key] = cell.value
            elif cell.key.kind == "text_ended":
                state.text_ended.add(key)
            elif cell.key.kind == "tool_call":
                state.tool_calls.add(key)
            elif cell.key.kind == "interrupt":
                state.checkpoint_interrupt_ids.add(key)
        return state

    def checkpoint_value(self, key: ProjectionCellKey) -> str | None:
        if key.kind == "text_message":
            return self.text_messages.get(key.key)
        members = {
            "text_ended": self.text_ended,
            "tool_call": self.tool_calls,
            "interrupt": self.checkpoint_interrupt_ids | self.open_interrupts.keys(),
        }
        if key.kind not in members:
            raise AgUiProjectionError("cell is not projector state")
        return "1" if key.key in members[key.kind] else None
