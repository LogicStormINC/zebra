"""A narrowing failure that must stop the accepted Turn without model retry."""

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult

PLUGIN_UNAVAILABLE = "plugin_authority_unavailable"


class PluginSelectionRefused(ValueError):
    """A known explicit selection cannot be admitted under the frozen ceiling."""


class PluginAuthorityUnavailable(RuntimeError):
    """A frozen component no longer has an admitted, currently valid source."""


def plugin_unavailable_result(call: ToolCall) -> ToolResult:
    return ToolResult(
        tool_call_id=call.tool_call_id,
        status=ToolCallStatus.FAILED,
        output="The accepted plugin authority is unavailable. Execution is suspended.",
        metadata={
            "reason": PLUGIN_UNAVAILABLE,
            "category": "plugin_authority",
            "retryable": False,
            "execution_state": "not_executed",
        },
    )
