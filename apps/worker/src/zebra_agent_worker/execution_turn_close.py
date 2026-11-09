"""Close a Turn and its Segment with the executing Attempt identity."""

from uuid import UUID

from agent_core.application import current_turn
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.turns import InteractionMode, derive_turn_id
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports import EventStorePort

from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_input_preparation import ExecutionInputEventView


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
    if isinstance(event_store, ExecutionInputEventView):
        # ponytail: closure needs the admitted identity, not a new model-input replay.
        # Recorder writes still enforce fresh control state, sequence and lease fencing.
        open_turn = event_store.admitted_turn
        fallback: UUID = recorder.session.session_id
    else:
        events = (
            event_store.list_for_session(recorder.session.session_id)
            if event_store is not None else []
        )
        open_turn = current_turn(events) if events else None
        fallback = (events[0].session_id if events else
                    getattr(recorder.session, "session_id", None) or UUID(int=0))
    turn_id = open_turn.turn_id if open_turn else str(derive_turn_id(fallback, 0))
    turn_index = open_turn.turn_index if open_turn else 0
    completed = attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    closes_segment = not completed or interaction_mode is not InteractionMode.CONVERSATION
    # CA-HA-03 D3: the close burst commits as one atomic batch when the recorder
    # supports it; per-Event fallback preserves the legacy semantics otherwise.
    turn_type = EventType.TURN_COMPLETED if completed else EventType.TURN_FAILED
    turn_payload = {
        "turn_id": turn_id,
        "turn_index": turn_index,
        "summary" if completed else "reason": attempt_result.summary,
        "closes_segment": closes_segment,
        "attempt_number": attempt_number,
        "metadata": attempt_result.metadata,
    }
    if closes_segment:
        terminal_type = EventType.SESSION_COMPLETED if completed else EventType.SESSION_FAILED
        terminal_payload = {
            "attempt_number": attempt_number,
            "summary": attempt_result.summary,
            "metadata": attempt_result.metadata,
        }
        # Duck-typed recorders and non-batch stores keep the exact per-Event path.
        append_close_batch = getattr(recorder, "append_close_batch", None)
        if append_close_batch is not None:
            append_close_batch([
                (turn_type, EventActor.HARNESS, turn_payload),
                (terminal_type, EventActor.HARNESS, terminal_payload),
            ])
        else:
            recorder.append(turn_type, EventActor.HARNESS, turn_payload)
            recorder.append(terminal_type, EventActor.HARNESS, terminal_payload)
    else:
        recorder.append(turn_type, EventActor.HARNESS, turn_payload)
