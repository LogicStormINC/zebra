from agent_core.domain.clarifications import (
    MAX_CLARIFICATION_CHOICE_CHARS,
    MAX_CLARIFICATION_CHOICES,
    MAX_CLARIFICATION_CONTEXT_CHARS,
    MAX_CLARIFICATION_QUESTION_CHARS,
)
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult

from agent_tools.contracts import ToolContract

clarify_contract = ToolContract(
    name="agent.clarify",
    required_arguments=("question",),
    description=(
        "Pause the parent session and ask the user for required information. "
        "Use only when a consequential ambiguity cannot be resolved safely."
    ),
    argument_properties={
        "question": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_CLARIFICATION_QUESTION_CHARS,
            "description": "One direct question without embedded option numbering.",
        },
        "choices": {
            "type": "array",
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_CLARIFICATION_CHOICE_CHARS,
            },
            "maxItems": MAX_CLARIFICATION_CHOICES,
            "description": "Up to four distinct offered answers; omit for free text.",
        },
        "context": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_CLARIFICATION_CONTEXT_CHARS,
            "description": "Optional concise explanation of why this answer is required.",
        },
    },
)


class ClarifyTool:
    @property
    def contract(self) -> ToolContract:
        return clarify_contract

    @staticmethod
    def handle(tool_call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.FAILED,
            output="",
            metadata={
                "reason": "clarification_requires_harness",
                "detail": "agent.clarify may only execute as a parent Harness stop point",
            },
        )
