from datetime import UTC, datetime

from agent_core.domain.identifiers import new_session_id, new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_tools import ArtifactReadTool


class StaticArtifactReader:
    def __init__(self, content: str) -> None:
        self.content = content

    def read_payload_bytes(self, _session_id, _uri: str) -> bytes:
        return self.content.encode()

    def describe_payload(self, _session_id, _uri: str):
        return None

    def inspect_payload(self, _session_id, _uri: str):
        return None


def test_artifact_reader_returns_explicit_segment_coverage() -> None:
    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="artifacts.read",
        arguments={"uri": "artifact://snapshot", "offset": 4, "max_characters": 5},
        created_at=datetime(2026, 9, 20, tzinfo=UTC),
    )

    result = ArtifactReadTool(StaticArtifactReader("0123456789"), new_session_id()).handle(call)

    assert result.status is ToolCallStatus.EXECUTED
    assert result.output == "45678"
    assert result.metadata["coverage"] == {
        "included_start": 4,
        "included_end": 9,
        "total_characters": 10,
    }
    assert result.metadata["has_more"] is True
    assert result.metadata["next_cursor"] == 9
