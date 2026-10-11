from datetime import UTC, datetime, timedelta

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_event_id, new_session_id
from agent_observability import summarize_execution_latencies


def test_execution_latency_summary_is_bounded_and_identity_free() -> None:
    origin = datetime(2026, 9, 20, tzinfo=UTC)
    session_id = new_session_id()
    raw = (
        (EventType.SESSION_COMMAND_ACCEPTED, 0),
        (EventType.HARNESS_ATTEMPT_STARTED, 40),
        (EventType.MODEL_REQUEST_STARTED, 50),
        (EventType.MODEL_RESPONSE_RECEIVED, 150),
        (EventType.MODEL_REQUEST_STARTED, 200),
        (EventType.MODEL_RESPONSE_RECEIVED, 700),
        (EventType.TOOL_EXECUTION_STARTED, 710),
        (EventType.TURN_COMPLETED, 900),
    )
    events = tuple(
        SessionEvent.model_construct(
            event_id=new_event_id(),
            session_id=session_id,
            sequence=sequence,
            event_type=event_type,
            payload={},
            actor=EventActor.SYSTEM,
            created_at=origin + timedelta(milliseconds=milliseconds),
            causation_id=None,
            correlation_id=None,
            idempotency_key=None,
            policy_version=None,
            model_profile=None,
        )
        for sequence, (event_type, milliseconds) in enumerate(raw)
    )

    summaries = {item.stage: item for item in summarize_execution_latencies(events)}

    assert summaries["queue_wait"].p50_ms == 40
    assert summaries["model"].observations == 2
    assert summaries["model"].p50_ms == 100
    assert summaries["model"].p95_ms == 500
    assert summaries["tool"].observations == 0
    assert summaries["tool"].incomplete == 1
    assert summaries["turn"].maximum_ms == 860
    assert not hasattr(summaries["turn"], "session_id")


def test_negative_clock_skew_never_emits_negative_latency() -> None:
    origin = datetime(2026, 9, 20, tzinfo=UTC)
    session_id = new_session_id()
    events = tuple(
        SessionEvent.model_construct(
            event_id=new_event_id(),
            session_id=session_id,
            sequence=sequence,
            event_type=event_type,
            payload={},
            actor=EventActor.SYSTEM,
            created_at=created_at,
            causation_id=None,
            correlation_id=None,
            idempotency_key=None,
            policy_version=None,
            model_profile=None,
        )
        for sequence, (event_type, created_at) in enumerate(
            (
                (EventType.MODEL_REQUEST_STARTED, origin),
                (EventType.MODEL_RESPONSE_RECEIVED, origin - timedelta(seconds=1)),
            )
        )
    )

    model = next(
        item for item in summarize_execution_latencies(events) if item.stage == "model"
    )

    assert model.maximum_ms == 0


def test_parallel_tools_pair_by_call_and_session_not_fifo() -> None:
    origin = datetime(2026, 9, 20, tzinfo=UTC)
    first, second = new_session_id(), new_session_id()
    rows = (
        (first, 1, EventType.TOOL_EXECUTION_STARTED, "slow", 0),
        (first, 2, EventType.TOOL_EXECUTION_STARTED, "fast", 100),
        (first, 3, EventType.TOOL_EXECUTION_COMPLETED, "fast", 200),
        (first, 4, EventType.TOOL_EXECUTION_FAILED, "slow", 900),
        (second, 1, EventType.TOOL_EXECUTION_STARTED, "slow", 300),
        (second, 2, EventType.TOOL_EXECUTION_COMPLETED, "slow", 600),
    )
    events = tuple(SessionEvent.model_construct(
        event_id=new_event_id(), session_id=session_id, sequence=sequence,
        event_type=kind, payload={"tool_call_id": call}, actor=EventActor.SYSTEM,
        created_at=origin + timedelta(milliseconds=milliseconds),
    ) for session_id, sequence, kind, call, milliseconds in rows)
    tool = next(item for item in summarize_execution_latencies(events) if item.stage == "tool")
    assert tool.observations == 3 and tool.incomplete == 0
    assert tool.p50_ms == 300 and tool.maximum_ms == 900
