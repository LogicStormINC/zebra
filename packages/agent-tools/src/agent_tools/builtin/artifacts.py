from agent_core.domain.identifiers import SessionId
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports import ArtifactPayloadReadPort

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError

artifact_read_contract = ToolContract(
    name="artifacts.read",
    parallel_safe=True,
    required_arguments=("uri",),
    description="Read a bounded segment from an Artifact snapshot in this session.",
    argument_properties={
        "uri": {"type": "string", "description": "Canonical artifact:// URI."},
        "offset": {"type": "integer", "minimum": 0},
        "max_characters": {"type": "integer", "minimum": 1, "maximum": 16000},
    },
)


class ArtifactReadTool:
    def __init__(self, reader: ArtifactPayloadReadPort, session_id: SessionId) -> None:
        self._reader = reader
        self._session_id = session_id

    @property
    def contract(self) -> ToolContract:
        return artifact_read_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        uri = tool_call.arguments.get("uri")
        offset = tool_call.arguments.get("offset", 0)
        limit = tool_call.arguments.get("max_characters", 8_192)
        if not isinstance(uri, str) or not uri.strip():
            raise ToolArgumentError("artifacts.read requires a non-blank uri")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ToolArgumentError("artifacts.read offset must be a non-negative integer")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 16_000:
            raise ToolArgumentError("artifacts.read max_characters must be between 1 and 16000")
        try:
            complete = self._reader.read_payload_bytes(self._session_id, uri.strip()).decode(
                "utf-8", errors="replace"
            )
        except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                metadata={"reason": "artifact_unavailable", "detail": str(exc)[:1000]},
            )
        visible = complete[offset : offset + limit]
        end = offset + len(visible)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=visible or "[no content in requested range]",
            metadata={
                "artifact_uri": uri.strip(),
                "coverage": {
                    "included_start": offset,
                    "included_end": end,
                    "total_characters": len(complete),
                },
                "truncated": end < len(complete),
                "has_more": end < len(complete),
                "next_cursor": end if end < len(complete) else None,
            },
        )
