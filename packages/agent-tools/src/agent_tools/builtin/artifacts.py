import re

from agent_core.domain.identifiers import SessionId
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports import ArtifactPayloadReadPort

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError

artifact_read_contract = ToolContract(
    name="artifacts.read",
    parallel_safe=True,
    required_arguments=("uri",),
    description=(
        "Read a bounded segment from an authorized Artifact snapshot in this session. "
        "Use query to locate a literal phrase and read its surrounding text instead of "
        "scanning a long document by offsets. Coverage uses original character offsets."
    ),
    argument_properties={
        "uri": {"type": "string", "description": "Canonical artifact:// URI."},
        "offset": {"type": "integer", "minimum": 0},
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": 256,
            "description": (
                "Optional case-insensitive literal phrase, not a regular expression. "
                "Finds the first match at or after offset and returns bounded surrounding "
                "text. Use next_cursor to continue; no match applies only from offset."
            ),
        },
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
        query = tool_call.arguments.get("query")
        if not isinstance(uri, str) or not uri.strip():
            raise ToolArgumentError("artifacts.read requires a non-blank uri")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ToolArgumentError("artifacts.read offset must be a non-negative integer")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 16_000:
            raise ToolArgumentError("artifacts.read max_characters must be between 1 and 16000")
        if "query" in tool_call.arguments and (
            not isinstance(query, str) or not query.strip() or len(query) > 256
        ):
            raise ToolArgumentError(
                "artifacts.read query must be a nonblank literal up to 256 characters"
            )
        if isinstance(query, str) and len(query) > limit:
            raise ToolArgumentError("artifacts.read max_characters must fit the complete query")
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
        offset = min(offset, len(complete))
        start = offset
        match = None
        if isinstance(query, str):
            match = re.compile(re.escape(query), re.IGNORECASE).search(complete, offset)
            if match is not None:
                start = max(offset, match.start() - (limit - len(query)) // 3)
        visible = complete[start : start + limit] if query is None or match else ""
        end = start + len(visible)
        more = end < len(complete) and (query is None or match is not None)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=visible
            or (
                "[no literal match at or after offset]"
                if query is not None
                else "[no content in requested range]"
            ),
            metadata={
                "artifact_uri": uri.strip(),
                "coverage": {
                    "included_start": start,
                    "included_end": end,
                    "total_characters": len(complete),
                    **(
                        {
                            "search_start": offset,
                            "matched": match is not None,
                            **(
                                {"match_start": match.start(), "match_end": match.end()}
                                if match is not None
                                else {}
                            ),
                        }
                        if query is not None
                        else {}
                    ),
                },
                "truncated": more,
                "has_more": more,
                "next_cursor": end if more else None,
            },
        )
