from agent_core.domain.plans import (
    MAX_PLAN_STEP_CONTENT_CHARS,
    MAX_PLAN_STEP_ID_CHARS,
    MAX_PLAN_STEPS,
    PlanStepStatus,
)
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult

from agent_tools.contracts import ToolContract

plan_contract = ToolContract(
    name="agent.plan",
    description=(
        "Read or replace the parent session's durable task plan. Omit steps to read. "
        "For complex work, keep one concise ordered plan and update statuses promptly."
    ),
    argument_properties={
        "steps": {
            "type": "array",
            "maxItems": MAX_PLAN_STEPS,
            "description": "Complete replacement plan; use an empty list to clear it.",
            "items": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_PLAN_STEP_ID_CHARS,
                    },
                    "content": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_PLAN_STEP_CONTENT_CHARS,
                    },
                    "status": {
                        "type": "string",
                        "enum": [status.value for status in PlanStepStatus],
                    },
                },
                "required": ["step_id", "content", "status"],
                "additionalProperties": False,
            },
        }
    },
)


class PlanTool:
    @property
    def contract(self) -> ToolContract:
        return plan_contract

    @staticmethod
    def handle(tool_call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.FAILED,
            metadata={
                "reason": "plan_requires_harness",
                "detail": "agent.plan may only execute inside the parent Harness",
            },
        )
