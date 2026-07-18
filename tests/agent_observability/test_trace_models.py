from datetime import UTC, datetime

import pytest
from agent_core.contracts.events import EventPayloadValidationError, validate_event_payload
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_observability import CostSummary, build_trace_record


def _event(
    event_type: EventType,
    *,
    sequence: int,
    payload: dict[str, object] | None = None,
    session_id: SessionId | None = None,
) -> SessionEvent:
    return SessionEvent.create(
        session_id=session_id or new_session_id(),
        sequence=sequence,
        event_type=event_type,
        actor=EventActor.HARNESS,
        payload=payload,
        created_at=datetime(2026, 6, 22, 17, 0, tzinfo=UTC),
    )


def test_build_trace_record_summarizes_events_tools_and_cost() -> None:
    session_id = new_session_id()
    events = (
        _event(
            EventType.SESSION_CREATED,
            sequence=0,
            payload={"title": "trace"},
            session_id=session_id,
        ),
        _event(
            EventType.MODEL_RESPONSE_RECEIVED,
            sequence=1,
            payload={
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "reasoning_tokens": 2,
                "prompt_cache_hit_tokens": 7,
                "prompt_cache_miss_tokens": 3,
                "cost_usd": 0.02,
                "profile_id": "deepseek-v4-pro-reviewer-v1",
                "profile_version_observed_at": "2026-07-17",
                "provider": "deepseek",
                "requested_model": "deepseek-v4-pro",
                "resolved_model": "deepseek-v4-pro",
                "role": "reviewer",
                "thinking_mode": "enabled",
                "reasoning_effort": "high",
                "tool_choice": "none",
                "prompt_version": "zebra-deepseek-chat-v1",
                "tool_schema_bytes": 128,
                "tool_schema_hash": "schema-hash",
                "stable_prefix_hash": "prefix-hash",
                "estimated_input_tokens": 12,
                "input_token_limit": 114_000,
                "token_estimate_method": "chars_div_4",
                "input_token_estimate_error": -2,
                "finish_reason": "stop",
                "time_to_first_event_ms": 20,
                "time_to_first_public_text_ms": 50,
                "latency_ms": 200,
                "retry_count": 1,
                "system_fingerprint": "fp-1",
            },
            session_id=session_id,
        ),
        _event(
            EventType.TOOL_EXECUTION_COMPLETED,
            sequence=2,
            payload={
                "attempt_number": 1,
                "tool_name": "tests.run",
                "status": "executed",
                "output": "ok",
                "metadata": {},
            },
            session_id=session_id,
        ),
    )

    trace = build_trace_record(events)

    assert trace.session_id == str(session_id)
    assert trace.event_count == 3
    assert trace.tool_result_count == 1
    assert trace.cost.model_calls == 1
    assert trace.cost.input_tokens == 10
    assert trace.cost.output_tokens == 5
    assert trace.cost.total_tokens == 15
    assert trace.cost.reasoning_tokens == 2
    assert trace.cost.prompt_cache_hit_tokens == 7
    assert trace.cost.prompt_cache_miss_tokens == 3
    assert trace.cost.cost_usd == 0.02
    assert trace.model_calls[0].profile_id == "deepseek-v4-pro-reviewer-v1"
    assert trace.model_calls[0].resolved_model == "deepseek-v4-pro"
    assert trace.model_calls[0].time_to_first_public_text_ms == 50
    assert trace.model_calls[0].retry_count == 1
    assert trace.model_calls[0].prompt_version == "zebra-deepseek-chat-v1"
    assert trace.model_calls[0].tool_schema_bytes == 128
    assert trace.model_calls[0].stable_prefix_hash == "prefix-hash"
    assert [record.sequence for record in trace.audit] == [0, 1, 2]


def test_build_trace_record_rejects_empty_event_stream() -> None:
    with pytest.raises(ValueError, match="at least one event"):
        build_trace_record(())


def test_build_trace_record_rejects_mixed_sessions() -> None:
    events = (
        _event(EventType.SESSION_CREATED, sequence=0, payload={"title": "one"}),
        _event(
            EventType.TASK_PREPARED,
            sequence=1,
            payload={"title": "one", "user_input": "continue"},
        ),
    )

    with pytest.raises(ValueError, match="one session"):
        build_trace_record(events)


def test_cost_summary_rejects_negative_values() -> None:
    with pytest.raises(ValueError, match="cost_usd"):
        CostSummary(cost_usd=-1)


def test_model_response_contract_rejects_private_reasoning_content() -> None:
    with pytest.raises(EventPayloadValidationError):
        validate_event_payload(
            EventType.MODEL_RESPONSE_RECEIVED,
            {
                "assistant_message": "public answer",
                "reasoning_content": "private chain",
            },
        )
