"""Project Turn records from the Session Event stream (ADR-026).

Turns are projections, not a second source of truth: no authoritative
``turns`` table exists. Streams written before ADR-026 replay as legacy
one-shot turns with synthesized identities.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.turns import InteractionMode, TurnStatus, resolve_interaction_mode

_TURN_TERMINAL_EVENTS = (
    EventType.TURN_COMPLETED,
    EventType.TURN_FAILED,
    EventType.TURN_CANCELLED,
)


@dataclass(frozen=True, slots=True)
class TurnRecord:
    turn_id: str
    turn_index: int
    status: TurnStatus
    opened_sequence: int
    origin: str
    closed_sequence: int | None = None
    summary: str | None = None
    closes_segment: bool | None = None
    legacy: bool = False


def is_human_message(event: SessionEvent) -> bool:
    """A real human message, never a handoff/automation seed."""

    if event.event_type is not EventType.USER_MESSAGE_RECEIVED:
        return False
    return (
        event.payload.get("actor_kind") != "automation"
        and event.payload.get("source") != "session_handoff"
    )


def interaction_mode_of(events: list[SessionEvent] | tuple[SessionEvent, ...]) -> InteractionMode:
    for event in events:
        if event.event_type is EventType.TASK_PREPARED:
            raw = event.payload.get("interaction_mode")
            if not isinstance(raw, str):
                raw = None
            return resolve_interaction_mode(raw)
    return resolve_interaction_mode(None)


def project_turns(events: list[SessionEvent] | tuple[SessionEvent, ...]) -> tuple[TurnRecord, ...]:
    """Replay Turn records from one Segment's event stream.

    New-style streams open turns via ``USER_MESSAGE_RECEIVED.turn_id`` and
    close them via ``TURN_*`` events. Legacy streams synthesize one turn per
    human message, closed by the Segment terminal event that legacy
    finalization always wrote.
    """

    records: list[TurnRecord] = []
    open_by_id: dict[str, TurnRecord] = {}
    turn_index = 0

    for event in events:
        if event.event_type is EventType.USER_MESSAGE_RECEIVED:
            payload_turn_id = event.payload.get("turn_id")
            payload_turn_index = event.payload.get("turn_index")
            if not is_human_message(event):
                continue
            if isinstance(payload_turn_id, str) and payload_turn_id.strip():
                index = (
                    payload_turn_index
                    if isinstance(payload_turn_index, int) and payload_turn_index >= 0
                    else turn_index
                )
                record = TurnRecord(
                    turn_id=payload_turn_id.strip(),
                    turn_index=index,
                    status=TurnStatus.RUNNING,
                    opened_sequence=event.sequence,
                    origin="human",
                )
                records.append(record)
                open_by_id[record.turn_id] = record
                turn_index = index + 1
            elif not _any_open(records):
                # Legacy replay: one implicit turn per human message.
                record = TurnRecord(
                    turn_id=f"legacy-turn:{event.sequence}",
                    turn_index=turn_index,
                    status=TurnStatus.RUNNING,
                    opened_sequence=event.sequence,
                    origin="human",
                    legacy=True,
                )
                records.append(record)
                open_by_id[record.turn_id] = record
                turn_index += 1
        elif event.event_type in _TURN_TERMINAL_EVENTS:
            payload_turn_id = event.payload.get("turn_id")
            if not isinstance(payload_turn_id, str):
                continue
            closing: TurnRecord | None = open_by_id.get(payload_turn_id.strip())
            if closing is None or closing.status not in {
                TurnStatus.RUNNING,
                TurnStatus.WAITING_APPROVAL,
                TurnStatus.WAITING_INPUT,
            }:
                continue
            if event.event_type is EventType.TURN_COMPLETED:
                status = TurnStatus.COMPLETED
            elif event.event_type is EventType.TURN_FAILED:
                status = TurnStatus.FAILED
            else:
                status = TurnStatus.CANCELLED
            closes_segment = event.payload.get("closes_segment")
            closed = TurnRecord(
                turn_id=closing.turn_id,
                turn_index=closing.turn_index,
                status=status,
                opened_sequence=closing.opened_sequence,
                origin=closing.origin,
                closed_sequence=event.sequence,
                summary=_summary_of(event),
                closes_segment=isinstance(closes_segment, bool) and closes_segment,
                legacy=closing.legacy,
            )
            _replace_record(records, open_by_id, closing, closed)
        elif event.event_type is EventType.APPROVAL_REQUESTED:
            _mutate_open(records, open_by_id, TurnStatus.WAITING_APPROVAL)
        elif event.event_type is EventType.CLARIFICATION_REQUESTED:
            _mutate_open(records, open_by_id, TurnStatus.WAITING_INPUT)
        elif event.event_type in {
            EventType.APPROVAL_GRANTED,
            EventType.CLARIFICATION_RESPONDED,
        }:
            _mutate_open(records, open_by_id, TurnStatus.RUNNING)
        elif event.event_type in {
            EventType.SESSION_COMPLETED,
            EventType.SESSION_FAILED,
            EventType.SESSION_CANCELLED,
        }:
            # Legacy streams close any still-open turn at the Segment
            # terminal; new-style streams have no open turn left here.
            _mutate_open(
                records,
                open_by_id,
                TurnStatus.COMPLETED
                if event.event_type is EventType.SESSION_COMPLETED
                else TurnStatus.FAILED
                if event.event_type is EventType.SESSION_FAILED
                else TurnStatus.CANCELLED,
                closed_sequence=event.sequence,
                legacy_close=True,
            )

    return tuple(records)


def current_turn(events: list[SessionEvent] | tuple[SessionEvent, ...]) -> TurnRecord | None:
    records = project_turns(events)
    for record in reversed(records):
        if record.status in {
            TurnStatus.RUNNING,
            TurnStatus.WAITING_APPROVAL,
            TurnStatus.WAITING_INPUT,
        }:
            return record
    return None


def latest_completed_turn(
    events: list[SessionEvent] | tuple[SessionEvent, ...],
) -> TurnRecord | None:
    records = project_turns(events)
    for record in reversed(records):
        if record.status is TurnStatus.COMPLETED:
            return record
    return None


def _any_open(records: list[TurnRecord]) -> bool:
    return any(
        record.status in {TurnStatus.RUNNING, TurnStatus.WAITING_APPROVAL, TurnStatus.WAITING_INPUT}
        for record in records
    )


def _replace_record(
    records: list[TurnRecord],
    open_by_id: dict[str, TurnRecord],
    previous: TurnRecord,
    updated: TurnRecord,
) -> None:
    for position, record in enumerate(records):
        if record is previous:
            records[position] = updated
            break
    open_by_id[updated.turn_id] = updated


def _mutate_open(
    records: list[TurnRecord],
    open_by_id: dict[str, TurnRecord],
    status: TurnStatus,
    *,
    closed_sequence: int | None = None,
    legacy_close: bool = False,
) -> None:
    for position, record in enumerate(records):
        if record.status not in {
            TurnStatus.RUNNING,
            TurnStatus.WAITING_APPROVAL,
            TurnStatus.WAITING_INPUT,
        }:
            continue
        updated = TurnRecord(
            turn_id=record.turn_id,
            turn_index=record.turn_index,
            status=status,
            opened_sequence=record.opened_sequence,
            origin=record.origin,
            closed_sequence=(
                closed_sequence if closed_sequence is not None else record.closed_sequence
            ),
            summary=record.summary,
            closes_segment=record.closes_segment,
            legacy=record.legacy,
        )
        records[position] = updated
        open_by_id[updated.turn_id] = updated
        if legacy_close:
            return


def _summary_of(event: SessionEvent) -> str | None:
    summary = event.payload.get("summary")
    return summary if isinstance(summary, str) else None
