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
    hit = coverage["matches"][0]
    assert hit["start"] == content.index("A.[B]")
    assert hit["end"] == content.index("A.[B]") + 5
    ((start, end),) = coverage["included_ranges"]
    assert result.output == content[start:end]
    assert "A.[B]" in result.output and len(result.output) == 17
    assert result.metadata["next_cursor"] is None
    assert coverage["literal_match"] is True
    assert coverage["candidate_only"] is False


def test_query_continuation_and_no_match_do_not_claim_unseen_text() -> None:
    tool = ArtifactReadTool(StaticArtifactReader("MATCH" + "x" * 25 + "match"), new_session_id())
    first = tool.handle(read_call(query="match", max_characters=10))
    second = tool.handle(
        read_call(query="match", offset=first.metadata["next_cursor"], max_characters=10)
    )
    assert first.metadata["coverage"]["matches"][0]["start"] == 0
    assert second.metadata["coverage"]["matches"][0]["start"] == 30
    assert second.metadata["has_more"] is False
    missing = tool.handle(read_call(query="missing", offset=10))
    coverage = missing.metadata["coverage"]
    assert coverage["literal_match"] is False and coverage["candidate_only"] is True
    assert coverage["included_ranges"] == [] and coverage["matches"] == []
    assert coverage["search_start"] == 10 and not missing.output
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


def assert_exact_excerpts(result, content, limit):
    import json

    from agent_core.harness.model_step_support import tool_result_content

    coverage = result.metadata["coverage"]
    ranges = coverage["included_ranges"]
    assert len(result.output) <= limit and len(ranges) <= 4
    prefix = (
        "[Unverified word candidates; literal phrase not found]\n"
        if coverage["candidate_only"] and ranges
        else ""
    )
    assert result.output == prefix + "\n\n[Next snapshot excerpt]\n\n".join(
        content[start:end] for start, end in ranges
    )
    for i, (start, end) in enumerate(ranges):
        assert 0 <= start < end <= len(content) and end - start <= 2048
        assert all(end <= a or start >= b for a, b in ranges[:i])
        hit = coverage["matches"][i]
        assert start <= hit["start"] < hit["end"] <= end
    observation = json.loads(tool_result_content(result))
    assert observation["coverage"] == coverage


def test_multiple_literal_excerpts_include_later_body_and_share_budget():
    content = "Table Of Contents\n2.2. Concurrency\n" + "x" * 3000
    content += "\n2.2. Concurrency\nOnly one writer at a time.\n" + "y" * 3000
    tool = ArtifactReadTool(StaticArtifactReader(content), new_session_id())
    result = tool.handle(read_call(query="Concurrency", max_characters=4500))
    assert len(result.metadata["coverage"]["included_ranges"]) == 2
    assert "Only one writer" in result.output
    assert_exact_excerpts(result, content, 4500)


def test_metadata_and_code_are_labeled_without_claiming_semantics():
    content = '```json metadata\n{"title":"AOF disadvantages"}\n```\n' + "x" * 3000
    content += "\n## AOF disadvantages\nReal paragraph.\n" + "x" * 3000
    tool = ArtifactReadTool(StaticArtifactReader(content), new_session_id())
    result = tool.handle(read_call(query="AOF disadvantages"))
    assert [h["kind"] for h in result.metadata["coverage"]["matches"]] == [
        "fenced_metadata",
        "text",
    ]
    assert "Real paragraph" in result.output
    assert_exact_excerpts(result, content, 8192)
    for fence in ("```go", "~~~go"):
        code = fence + "\nredisClient := rdb.VAdd()\n"
        result = ArtifactReadTool(StaticArtifactReader(code), new_session_id()).handle(
            read_call(query="RDB")
        )
        assert result.metadata["coverage"]["matches"][0]["kind"] == "fenced_code"
        assert_exact_excerpts(result, code, 8192)


def test_word_candidates_are_unverified_and_do_not_invent_synonyms():
    content = "Unrelated add operation.\n\n" + "x" * 3000
    content += "\n\nAdd an asynchronous I/O subsystem. Reads can run concurrently."
    tool = ArtifactReadTool(StaticArtifactReader(content), new_session_id())
    result = tool.handle(read_call(query="Add asynchronous I/O", max_characters=3000))
    coverage = result.metadata["coverage"]
    assert coverage["literal_match"] is False and coverage["candidate_only"] is True
    assert content[coverage["matches"][0]["start"] :].startswith("Add an asynchronous")
    assert "Unverified word candidates" in result.output
    assert result.metadata["next_cursor"] is None
    assert_exact_excerpts(result, content, 3000)
    no_synonym = ArtifactReadTool(StaticArtifactReader("Vector set [preview]"), new_session_id())
    absent = no_synonym.handle(read_call(query="beta"))
    assert not absent.output and absent.metadata["coverage"]["included_ranges"] == []


def test_query_limits_and_continuation_never_expand_global_budget():
    content = ("TOKEN" + "x" * 3000 + "\n\n") * 6
    tool = ArtifactReadTool(StaticArtifactReader(content), new_session_id())
    for limit in (5, 17, 120, 2048, 8192, 16000):
        result = tool.handle(read_call(query="TOKEN", max_characters=limit))
        assert_exact_excerpts(result, content, limit)
        cursor = result.metadata["next_cursor"]
        assert cursor is not None and cursor > 0
        next_result = tool.handle(read_call(query="TOKEN", offset=cursor, max_characters=limit))
        assert next_result.metadata["coverage"]["matches"][0]["start"] == cursor
        assert_exact_excerpts(next_result, content, limit)
    for limit in (7, 55, 56, 120):
        result = tool.handle(read_call(query="TOKEN missing", max_characters=max(limit, 13)))
        assert_exact_excerpts(result, content, max(limit, 13))
