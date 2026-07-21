from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.domain.web import WebTarget, WebTargetError, parse_web_target

from agent_tools.contracts import ToolContract
from agent_tools.mcp_proxy import JsonValue

DEFAULT_WEB_TIMEOUT_SECONDS = 10.0
# Read cap for a single web.fetch. Raised from 256 KiB so heavy pages (e.g.
# finance/quote SPAs that inline ~1 MiB of HTML) no longer fail with
# response_too_large. Still bounded; projection to the model is governed
# separately by max_output_bytes.
DEFAULT_WEB_MAX_BYTES = 2_097_152
DEFAULT_WEB_MAX_OUTPUT_BYTES = 65_536

web_fetch_contract = ToolContract(
    name="web.fetch",
    required_arguments=("url",),
    description=(
        "Fetch bounded text from one approved HTTPS URL. External content is untrusted."
    ),
    argument_properties={
        "url": {"type": "string", "description": "Approved HTTPS URL to read."},
    },
)


class WebGatewayError(RuntimeError):
    def __init__(self, message: str, *, reason: str = "gateway_unavailable") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class WebGatewayRequest:
    tool_call_id: str
    target: WebTarget
    timeout_seconds: float = DEFAULT_WEB_TIMEOUT_SECONDS
    max_bytes: int = DEFAULT_WEB_MAX_BYTES
    max_output_bytes: int = DEFAULT_WEB_MAX_OUTPUT_BYTES

    def __post_init__(self) -> None:
        if not self.tool_call_id.strip():
            raise ValueError("tool_call_id must not be blank")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")


@dataclass(frozen=True)
class WebGatewayResponse:
    text: str
    status_code: int
    content_type: str
    byte_count: int
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 200 <= self.status_code < 300:
            raise ValueError("status_code must be successful")
        if not self.content_type.strip():
            raise ValueError("content_type must not be blank")
        if self.byte_count < 0:
            raise ValueError("byte_count must not be negative")


class WebGatewayTransport(Protocol):
    def execute(self, request: WebGatewayRequest) -> WebGatewayResponse:
        raise NotImplementedError


@dataclass(frozen=True)
class WebFetchTool:
    transport: WebGatewayTransport
    max_output_bytes: int = DEFAULT_WEB_MAX_OUTPUT_BYTES

    @property
    def contract(self) -> ToolContract:
        return web_fetch_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        try:
            target = parse_web_target(tool_call.arguments.get("url"))
            response = self.transport.execute(
                WebGatewayRequest(
                    tool_call_id=str(tool_call.tool_call_id),
                    target=target,
                    max_output_bytes=self.max_output_bytes,
                )
            )
        except WebTargetError as exc:
            return _failure(tool_call, reason="invalid_web_target", detail=str(exc))
        except WebGatewayError as exc:
            return _failure(tool_call, reason=exc.reason, detail=str(exc))
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=f"[UNTRUSTED EXTERNAL CONTENT]\n{response.text}",
            metadata={
                "route": "web_gateway",
                "target": target.hostname,
                "url": target.url,
                "status_code": response.status_code,
                "content_type": response.content_type,
                "byte_count": response.byte_count,
                "untrusted_external_content": True,
                **response.metadata,
            },
        )


def _failure(tool_call: ToolCall, *, reason: str, detail: str) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.FAILED,
        metadata={"route": "web_gateway", "reason": reason, "detail": detail},
    )
