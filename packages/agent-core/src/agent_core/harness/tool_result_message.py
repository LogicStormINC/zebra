import json
from datetime import datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult


def tool_result_content(tool_result: ToolResult) -> str:
    if tool_result.output:
        return tool_result.output
    if tool_result.status is ToolCallStatus.EXECUTED:
        return "Tool executed."
    observation: dict[str, object] = {"status": tool_result.status.value}
    for key in ("reason", "detail"):
        value = tool_result.metadata.get(key)
        if isinstance(value, str | int | float | bool):
            observation[key] = value
    return json.dumps(observation, ensure_ascii=False, sort_keys=True)


def tool_result_status(tool_result: ToolResult) -> str:
    return "succeeded" if tool_result.status is ToolCallStatus.EXECUTED else "failed"


def tool_message_append_tool_batch(
    messages: list[SessionMessage],
    *,
    completion: ModelCompletion,
    tool_calls: tuple[ToolCall, ...],
) -> None:
    if not tool_calls:
        raise ValueError("tool batch must not be empty")
    messages.append(completion.assistant_message.model_copy(update={"tool_calls": tool_calls}))


def tool_message_append_tool_result(
    messages: list[SessionMessage],
    *,
    tool_call: ToolCall,
    tool_result: ToolResult,
    created_at: datetime,
) -> None:
    messages.append(
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.TOOL,
            content=tool_result_content(tool_result),
            created_at=created_at,
            tool_call_id=tool_call.provider_call_id or str(tool_call.tool_call_id),
            metadata={
                **tool_result.metadata,
                "tool_result_status": tool_result_status(tool_result),
            },
        )
    )
