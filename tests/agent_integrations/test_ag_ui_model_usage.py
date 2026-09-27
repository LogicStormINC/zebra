from datetime import UTC, datetime

from ag_ui.core import EventType as AgUiEventType
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_event_id, new_session_id
from agent_integrations.ag_ui import AgUiProjector, AgUiRunIdentity


def test_model_usage_is_projected_as_a_public_custom_event() -> None:
    session_id = new_session_id()
    event = SessionEvent(
        event_id=new_event_id(),
        session_id=session_id,
        sequence=0,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        actor=EventActor.HARNESS,
        created_at=datetime(2026, 8, 5, 8, 0, tzinfo=UTC),
        payload={
            "model_call_id": "model-usage",
            "assistant_message": "Done.",
            "input_tokens": 10_100,
            "input_token_limit": 105_000,
            "prompt_cache_hit_tokens": 96_800,
            "prompt_cache_miss_tokens": 3_200,
            "resolved_model": "deepseek/deepseek-flash",
            "reasoning_effort": "high",
            "token_breakdown": {
                "messages": 7_400,
                "system": 2_100,
                "tools": 600,
                "private": 999,
            },
            "token_breakdown_v2": {
                "schema_version": 2,
                "basis": "reconciled_provider_total",
                "estimate_method": "provider",
                "total_tokens": 10_100,
                "categories": {
                    "messages": 7_000,
                    "system_tools": 600,
                    "skills": 400,
                    "system_prompt": 1_500,
                    "mcp_tools": 500,
                    "other": 100,
                },
                "raw_estimated_total": 9_900,
                "provider_input_tokens": 10_100,
                "estimate_error": 200,
            },
            "stable_prefix_hash": "must-not-leave-zebra",
        },
    )

    projection = AgUiProjector().project(
        (event,),
        AgUiRunIdentity(session_id=session_id, thread_id="task-1", run_id="segment-1"),
    )
    usage = next(item for item in projection.events if item.type is AgUiEventType.CUSTOM)

    assert usage.name == "zebra.model_usage"
    assert usage.value == {
        "input_tokens": 10_100,
        "input_token_limit": 105_000,
        "prompt_cache_hit_tokens": 96_800,
        "prompt_cache_miss_tokens": 3_200,
        "resolved_model": "deepseek/deepseek-flash",
        "reasoning_effort": "high",
        "token_breakdown": {"messages": 7_400, "system": 2_100, "tools": 600},
        "token_breakdown_v2": {
            "schema_version": 2,
            "basis": "reconciled_provider_total",
            "estimate_method": "provider",
            "total_tokens": 10_100,
            "categories": {
                "messages": 7_000,
                "system_tools": 600,
                "skills": 400,
                "system_prompt": 1_500,
                "mcp_tools": 500,
                "other": 100,
            },
            "raw_estimated_total": 9_900,
            "provider_input_tokens": 10_100,
            "estimate_error": 200,
        },
    }
