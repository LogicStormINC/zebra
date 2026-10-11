"""Close a Turn and its Segment with the executing Attempt identity."""

from uuid import UUID

from agent_core.application import current_turn
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.turns import InteractionMode, derive_turn_id
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports import EventStorePort

from zebra_agent_worker.execution_events import DurableHarnessEventRecorder


def append_turn_close(
    *,
    recorder: DurableHarnessEventRecorder,
    attempt_result: HarnessAttemptResult,
    event_store: EventStorePort,
    interaction_mode: InteractionMode,
    attempt_number: int,
) -> None:
    """Conversation completion parks a Turn; failures close its Segment."""
    if type(attempt_number) is not int or attempt_number < 1:
        raise ValueError("invalid executing Attempt number")
    events = (
        event_store.list_for_session(recorder.session.session_id) if event_store is not None else []
    )
    open_turn = current_turn(events) if events else None
    fallback: UUID = (
        events[0].session_id
        if events
        else getattr(recorder.session, "session_id", None) or UUID(int=0)
    )
    turn_id = open_turn.turn_id if open_turn else str(derive_turn_id(fallback, 0))
    turn_index = open_turn.turn_index if open_turn else 0
    completed = attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    closes_segment = not completed or interaction_mode is not InteractionMode.CONVERSATION
    recorder.append(
        EventType.TURN_COMPLETED if completed else EventType.TURN_FAILED,
        EventActor.HARNESS,
        {
            "turn_id": turn_id,
            "turn_index": turn_index,
            "summary" if completed else "reason": attempt_result.summary,
            "closes_segment": closes_segment,
            "attempt_number": attempt_number,
            "metadata": attempt_result.metadata,
        },
    )
    if closes_segment:
        recorder.append(
            EventType.SESSION_COMPLETED if completed else EventType.SESSION_FAILED,
            EventActor.HARNESS,
            {
                "attempt_number": attempt_number,
                "summary": attempt_result.summary,
                "metadata": attempt_result.metadata,
            },
        )
