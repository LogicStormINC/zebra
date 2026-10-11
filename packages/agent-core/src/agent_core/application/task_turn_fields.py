"""Incremental public Turn fields, reusing the canonical Turn projection rules."""

from dataclasses import replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_core.application.turn_projection import TurnRecord, interaction_mode_of, project_turns
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.turns import InteractionMode, TurnStatus

_OPEN = {TurnStatus.RUNNING, TurnStatus.WAITING_APPROVAL, TurnStatus.WAITING_INPUT}


class SegmentTurnReadState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prepared: bool = False
    mode: InteractionMode = InteractionMode.ONE_SHOT
    records: tuple[TurnRecord, ...] = ()
    lookup: dict[str, int] = Field(default_factory=dict)
    human_turn_count: int = Field(default=0, ge=0, strict=True)

    def advance(self, event: SessionEvent) -> "SegmentTurnReadState":
        lookup = dict(self.lookup)
        records = project_turns((event,), initial=self.records, lookup=lookup)
        open_ids = {record.turn_id for record in records if record.status in _OPEN}
        # Keep the actual canonical lookup alias, not the last duplicate by order.
        # Closed IDs with no remaining open record need no historical target.
        retained = tuple(
            replace(record, summary=None)
            for record in records
            if record.status in _OPEN
            or record is records[-1]
            or record.turn_id in open_ids
            and record.opened_sequence == lookup[record.turn_id]
        )
        retained_sequences = {record.opened_sequence for record in retained}
        lookup = {record.turn_id: record.opened_sequence for record in retained} | {
            turn_id: sequence
            for turn_id, sequence in lookup.items()
            if sequence in retained_sequences
        }
        prepared = self.prepared or event.event_type is EventType.TASK_PREPARED
        mode = (
            interaction_mode_of((event,))
            if not self.prepared and event.event_type is EventType.TASK_PREPARED
            else self.mode
        )
        return SegmentTurnReadState(
            prepared=prepared,
            mode=mode,
            records=retained,
            lookup=lookup,
            human_turn_count=self.human_turn_count + len(records) - len(self.records),
        )

    def current_turn(self) -> TurnRecord | None:
        return next((record for record in reversed(self.records) if record.status in _OPEN), None)

    def public_fields(self) -> dict[str, object]:
        project_turns((), initial=self.records, lookup=dict(self.lookup))
        visible = next((r for r in reversed(self.records) if r.status in _OPEN), None)
        if visible is None and self.records:
            visible = self.records[-1]
        return {
            "interaction_mode": self.mode.value,
            "turn_id": visible.turn_id if visible else None,
            "current_turn_status": visible.status.value if visible else None,
        }


def advance_segment_turns(state: dict[str, Any], event: SessionEvent) -> None:
    key = str(event.session_id)
    prior = SegmentTurnReadState.model_validate(state.get(key, {}))
    state[key] = prior.advance(event).model_dump(mode="json")
