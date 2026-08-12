import json

from agent_core.domain.tools import ToolCallStatus, ToolResult


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
