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


def read_call(**arguments):
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="artifacts.read",
        arguments={"uri": "artifact://snapshot", **arguments},
        created_at=datetime.now(UTC),
    )


def test_literal_query_preserves_unicode_offsets_and_bounded_context() -> None:
    content = "İß中文" + "x" * 30 + "A.[B]" + "y" * 40
    tool = ArtifactReadTool(StaticArtifactReader(content), new_session_id())
    result = tool.handle(read_call(query="a.[b]", max_characters=17))
    coverage = result.metadata["coverage"]
    assert coverage["match_start"] == content.index("A.[B]")
    assert coverage["match_end"] == content.index("A.[B]") + 5
    assert result.output == content[coverage["included_start"] : coverage["included_end"]]
    assert "A.[B]" in result.output and len(result.output) == 17
    assert result.metadata["next_cursor"] == coverage["included_end"]


def test_query_continuation_and_no_match_do_not_claim_unseen_text() -> None:
    tool = ArtifactReadTool(StaticArtifactReader("MATCH" + "x" * 25 + "match"), new_session_id())
    first = tool.handle(read_call(query="match", max_characters=10))
    second = tool.handle(
        read_call(query="match", offset=first.metadata["next_cursor"], max_characters=10)
    )
    assert first.metadata["coverage"]["match_start"] == 0
    assert second.metadata["coverage"]["match_start"] == 30
    assert second.metadata["has_more"] is False
    missing = tool.handle(read_call(query="missing", offset=10))
    assert missing.metadata["coverage"] == {
        "included_start": 10,
        "included_end": 10,
        "total_characters": 35,
        "search_start": 10,
        "matched": False,
    }
    assert missing.metadata["next_cursor"] is None
    assert missing.metadata["has_more"] is False
    beyond = tool.handle(read_call(offset=100))
    assert beyond.metadata["coverage"]["included_start"] == 35
    assert beyond.metadata["coverage"]["included_end"] == 35


def test_query_validation_precedes_reader_and_authorization_is_preserved() -> None:
    import pytest
    from agent_tools.errors import ToolArgumentError

    class DeniedReader(StaticArtifactReader):
        def read_payload_bytes(self, session_id, uri):
            assert session_id == expected_session
            raise PermissionError("not this session")

    expected_session = new_session_id()
    tool = ArtifactReadTool(DeniedReader("secret"), expected_session)
    for query in (None, True, " ", "x" * 257):
        with pytest.raises(ToolArgumentError, match="query"):
            tool.handle(read_call(query=query))
    with pytest.raises(ToolArgumentError, match="fit"):
        tool.handle(read_call(query="length", max_characters=2))
    denied = tool.handle(read_call(query="secret"))
    assert denied.status is ToolCallStatus.FAILED
    assert denied.metadata["reason"] == "artifact_unavailable"
    assert not denied.output
