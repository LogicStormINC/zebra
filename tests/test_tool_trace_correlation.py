from datetime import UTC, datetime

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_event_id, new_session_id, new_tool_call_id
from agent_core.harness.projection import HarnessTraceProjector
from zebra_agent_api.serialization import serialize_trace_events as serialize_api_trace
from zebra_agent_cli.execution import serialize_trace_events as serialize_cli_trace

NOW = datetime(2026, 7, 15, 16, 0, tzinfo=UTC)


def test_correlated_parallel_same_name_calls_keep_exact_evidence() -> None:
    first_id = str(new_tool_call_id())
    second_id = str(new_tool_call_id())
    events = (
        _event(
            0,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"assistant_message": "Reading.", "attempt_number": 1},
        ),
        _proposal(1, first_id, "a.txt"),
        _policy(2, first_id, "allow"),
        _proposal(3, second_id, "b.txt"),
        _policy(4, second_id, "allow", route="mcp_proxy"),
        _terminal(5, second_id, "b.txt", "B"),
        _terminal(6, first_id, "a.txt", "A"),
    )

    attempts = HarnessTraceProjector().project_events(events)

    assert [tool.arguments for tool in attempts[0].tools] == [
        {"path": "b.txt"},
        {"path": "a.txt"},
    ]
    assert [tool.output for tool in attempts[0].tools] == ["B", "A"]
    assert [tool.policy_route for tool in attempts[0].tools] == ["mcp_proxy", None]

    api_tools = serialize_api_trace(events)[0]["tools"]
    cli_tools = serialize_cli_trace(events)[0]["tools"]
    assert [tool["arguments"] for tool in api_tools] == [
        {"path": "b.txt"},
        {"path": "a.txt"},
    ]
    assert [tool["arguments"] for tool in cli_tools] == [
        {"path": "b.txt"},
        {"path": "a.txt"},
    ]
    assert "tool_call_id" not in api_tools[0]
    assert "tool_call_id" not in cli_tools[0]


def test_legacy_same_name_calls_fall_back_to_provider_order() -> None:
    events = (
        _proposal(0, None, "legacy-a.txt"),
        _policy(1, None, "allow"),
        _proposal(2, None, "legacy-b.txt"),
        _policy(3, None, "deny"),
        _terminal(4, None, "legacy-a.txt", "A"),
        _terminal(5, None, "legacy-b.txt", "B"),
    )

    tools = HarnessTraceProjector().project_events(events)[0].tools

    assert [tool.arguments for tool in tools] == [
        {"path": "legacy-a.txt"},
        {"path": "legacy-b.txt"},
    ]
    assert [tool.policy_decision for tool in tools] == ["allow", "deny"]
    assert [tool.output for tool in tools] == ["A", "B"]


def _proposal(sequence: int, tool_call_id: str | None, path: str) -> SessionEvent:
    payload: dict[str, object] = {
        "attempt_number": 1,
        "tool_name": "files.read",
        "arguments": {"path": path},
    }
    if tool_call_id is not None:
        payload["tool_call_id"] = tool_call_id
    return _event(sequence, EventType.TOOL_CALL_PROPOSED, payload)


def _policy(
    sequence: int,
    tool_call_id: str | None,
    decision: str,
    *,
    route: str | None = None,
) -> SessionEvent:
    payload: dict[str, object] = {
        "attempt_number": 1,
        "tool_name": "files.read",
        "decision": decision,
    }
    if tool_call_id is not None:
        payload["tool_call_id"] = tool_call_id
    if route is not None:
        payload["route"] = route
    return _event(sequence, EventType.POLICY_DECISION_MADE, payload, EventActor.POLICY)


def _terminal(sequence: int, tool_call_id: str | None, path: str, output: str) -> SessionEvent:
    payload: dict[str, object] = {
        "attempt_number": 1,
        "tool_name": "files.read",
        "status": "executed",
        "output": output,
        "metadata": {"path": path},
    }
    if tool_call_id is not None:
        payload["tool_call_id"] = tool_call_id
    return _event(sequence, EventType.TOOL_EXECUTION_COMPLETED, payload, EventActor.TOOL)


def _event(
    sequence: int,
    event_type: EventType,
    payload: dict[str, object],
    actor: EventActor = EventActor.HARNESS,
) -> SessionEvent:
    return SessionEvent(
        event_id=new_event_id(),
        session_id=new_session_id(),
        sequence=sequence,
        event_type=event_type,
        payload=payload,
        actor=actor,
        created_at=NOW,
    )
