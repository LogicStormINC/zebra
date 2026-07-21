from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent_core.domain.clarifications import ClarificationContext


class McpElicitationDisabledError(ValueError):
    """Raised when elicitation/create arrives but ZEBRA_MCP_ELICITATION=off."""


@dataclass(frozen=True)
class ElicitationRequest:
    message: str
    requested_schema: dict[str, Any] | None


class McpElicitationBridge:
    """Convert an MCP ``elicitation/create`` payload into a durable ClarificationContext.

    Phase A is a synthesizer: the transports have no server-initiated JSON-RPC
    path yet, so the bridge is invoked once an elicitation payload has been
    detected. When disabled (``ZEBRA_MCP_ELICITATION=off``) it rejects
    ``elicitation/create`` with a structured error; the default is on. The
    converted context carries ``response_schema`` and ``elicitation_source`` so
    the existing durable clarification flow (CLARIFICATION_REQUESTED +
    WAITING_INPUT) handles it without a separate projection.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    @staticmethod
    def parse_elicitation_create(payload: object) -> ElicitationRequest:
        if not isinstance(payload, Mapping):
            raise ValueError("elicitation/create params must be an object")
        message = payload.get("message")
        requested_schema = payload.get("requestedSchema")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("elicitation/create requires a non-blank 'message'")
        if requested_schema is not None and not isinstance(requested_schema, dict):
            raise ValueError("elicitation/create 'requestedSchema' must be an object")
        return ElicitationRequest(message=message.strip(), requested_schema=requested_schema)

    def build_clarification_context(
        self,
        request: ElicitationRequest,
        *,
        tool_call_id: str,
        assistant_message: str,
        requested_at: datetime,
    ) -> ClarificationContext:
        if not self.enabled:
            raise McpElicitationDisabledError(
                "MCP elicitation is disabled (ZEBRA_MCP_ELICITATION=off)"
            )
        return ClarificationContext.from_elicitation(
            message=request.message,
            requested_schema=request.requested_schema,
            tool_call_id=tool_call_id,
            assistant_message=assistant_message,
            requested_at=requested_at,
        )

    @staticmethod
    def build_elicitation_result(action: str, content: str | None = None) -> dict[str, object]:
        if action not in {"accept", "decline", "cancel"}:
            raise ValueError("elicitation result action must be accept, decline, or cancel")
        result: dict[str, object] = {"action": action}
        if content is not None:
            result["content"] = content
        return result
