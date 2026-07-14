from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall
from agent_runtime import run_local_harness

NOW = datetime(2026, 7, 14, 15, 0, tzinfo=UTC)


def test_parent_uses_sourced_readonly_child_result_for_final_answer(tmp_path) -> None:
    (tmp_path / "evidence.txt").write_text("RESEARCH-EVIDENCE\n", encoding="utf-8")
    research_call = _call(
        "agent.research",
        {"objective": "Read evidence.txt and report its evidence."},
        "research_call",
    )
    read_call = _call("files.read", {"path": "evidence.txt"}, "read_call")
    gateway = ScriptedModelGateway(
        responses=tuple(
            ScriptedModelResponse(completion=completion)
            for completion in (
                _completion("Delegating research.", research_call),
                _completion("Reading evidence.", read_call),
                _completion("The sourced evidence is RESEARCH-EVIDENCE."),
                _completion("PARENT-ANSWER: RESEARCH-EVIDENCE"),
            )
        )
    )

    result = run_local_harness(
        prompt="Delegate evidence collection, then answer from the child result.",
        title="Read-only research delegation",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
    )

    assert result.attempt_result.metadata["assistant_message"] == (
        "PARENT-ANSWER: RESEARCH-EVIDENCE"
    )
    assert result.run_result.model_calls_used == 2
    assert result.run_result.tool_calls_used == 1
    assert "agent.research" in {tool.name for tool in gateway.tool_requests[0]}
    assert tuple(tool.name for tool in gateway.tool_requests[1]) == (
        "files.read",
        "git.status",
    )
    assert "agent.research" not in {tool.name for tool in gateway.tool_requests[1]}
    assert "evidence.txt" in gateway.requests[3][-1].content
    assert "RESEARCH-EVIDENCE" in gateway.requests[3][-1].content

    started = next(
        event for event in result.events if event.event_type is EventType.SUBAGENT_STARTED
    )
    completed = next(
        event for event in result.events if event.event_type is EventType.SUBAGENT_COMPLETED
    )
    assert started.payload["status"] == "running"
    assert completed.payload["status"] == "completed"
    assert completed.payload["source_count"] == 1
    assert completed.payload["confidence"] == 1.0
    assert "RESEARCH-EVIDENCE" not in str(started.payload)
    assert "RESEARCH-EVIDENCE" not in str(completed.payload)


def _completion(content: str, tool_call: ToolCall | None = None) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=NOW,
        ),
        tool_calls=(tool_call,) if tool_call is not None else (),
    )


def _call(name: str, arguments: dict[str, object], provider_id: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=NOW,
        provider_call_id=provider_id,
    )
