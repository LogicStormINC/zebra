from datetime import UTC, datetime

import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall
from agent_core.harness import HarnessModelStep, HarnessTask


def test_scripted_model_gateway_returns_deterministic_completion() -> None:
    created_at = datetime(2026, 6, 19, 21, 0, tzinfo=UTC)
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="I will inspect the repository.",
                        created_at=created_at,
                    )
                )
            ),
        )
    )
    step = HarnessModelStep()

    completion = step.request_initial_completion(
        HarnessTask(title="Inspect repo", user_input="Please inspect the repository."),
        gateway,
        created_at=created_at,
    )

    assert completion.assistant_message.content == "I will inspect the repository."
    assert len(gateway.requests) == 1
    assert gateway.requests[0][0].role is MessageRole.USER
    assert gateway.requests[0][0].content == "Please inspect the repository."


def test_scripted_model_gateway_supports_tool_call_planning_path() -> None:
    created_at = datetime(2026, 6, 19, 21, 5, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "README.md"},
        created_at=created_at,
    )
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="I will read the README first.",
                        created_at=created_at,
                    ),
                    tool_calls=(tool_call,),
                )
            ),
        )
    )
    step = HarnessModelStep()

    completion = step.request_initial_completion(
        HarnessTask(title="Review docs", user_input="Review the README before editing."),
        gateway,
        created_at=created_at,
    )

    assert completion.assistant_message.role is MessageRole.ASSISTANT
    assert len(completion.tool_calls) == 1
    assert completion.tool_calls[0].name == "files.read"
    assert completion.tool_calls[0].arguments == {"path": "README.md"}


def test_scripted_model_gateway_rejects_exhausted_script() -> None:
    created_at = datetime(2026, 6, 19, 21, 10, tzinfo=UTC)
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="one response only",
                        created_at=created_at,
                    )
                )
            ),
        )
    )
    request = [
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.USER,
            content="hello",
            created_at=created_at,
        )
    ]

    gateway.complete(request)

    with pytest.raises(RuntimeError, match="no remaining responses"):
        gateway.complete(request)
