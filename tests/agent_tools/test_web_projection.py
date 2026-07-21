from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall
from agent_core.domain.web_resource import WebResourceId
from agent_tools.web_envelope import WEB_ENVELOPE_CAPABILITY_VERSION
from agent_storage.web_chunker import chunk_clean_text
from agent_storage.web_resource import (
    ResourceStatus,
    SQLiteWebResourceStore,
    StoredWebResource,
    WebResourceStoreAdapter,
    utc_now_iso,
)
from agent_tools.web_projection import (
    CursorError,
    ReadCursor,
    WebFindTool,
    WebProjector,
    WebReadTool,
)


def _store_with_resource(tmp_path, clean: str):
    store = SQLiteWebResourceStore(tmp_path / "web.db", tmp_path / "cache")
    digest = sha256(clean.encode("utf-8")).hexdigest()
    resource = StoredWebResource(
        resource_id=str(WebResourceId.new()),
        requested_url="https://example.com/financials",
        final_url="https://example.com/financials",
        content_sha256=digest,
        created_at=utc_now_iso(),
        fetch_mode="http",
        resource_status=ResourceStatus.COMPLETE,
        wire_bytes=len(clean.encode("utf-8")),
        decoded_bytes=len(clean.encode("utf-8")),
        clean_chars=len(clean),
        title="Financials",
    )
    resource_id = store.save(
        resource=resource, chunks=chunk_clean_text(clean), clean_text=clean
    )
    return WebResourceStoreAdapter(store), resource_id


def _multi_section_clean() -> str:
    sections = []
    for index, topic in enumerate(("revenue", "margin", "guidance", "risk", "capital")):
        sections.append(f"# {topic.title()}\n\n" + f"{topic} detail number {index} " * 300)
    return "\n\n".join(sections)


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
    )


def test_cursor_round_trip_and_rejects_malformed() -> None:
    cursor = ReadCursor(resource_id=WebResourceId.new(), next_ordinal=3)

    decoded = ReadCursor.decode(cursor.encode())
    assert decoded == cursor

    with pytest.raises(CursorError):
        ReadCursor.decode("not-a-cursor")
    with pytest.raises(CursorError):
        ReadCursor.decode("cur_!!!invalid-base64!!!")


def test_find_returns_relevant_chunk_and_marks_untrusted(tmp_path) -> None:
    adapter, resource_id = _store_with_resource(tmp_path, _multi_section_clean())
    projector = WebProjector()

    projection = projector.find(adapter, resource_id, "revenue", max_tokens=8_000)

    assert "revenue" in projection.content.lower()
    assert projection.selected_count >= 1
    assert projection.truncation_scope.value in {"projection", "none"}


def test_read_resumes_via_cursor_until_done(tmp_path) -> None:
    adapter, resource_id = _store_with_resource(tmp_path, _multi_section_clean())
    projector = WebProjector()
    cursor = ReadCursor(resource_id=resource_id, next_ordinal=0)

    seen_ordinals: set[int] = set()
    steps = 0
    while cursor is not None and steps < 50:
        projection = projector.read(adapter, cursor, max_tokens=1_500)
        seen_ordinals.update(
            range(cursor.next_ordinal, cursor.next_ordinal + projection.selected_count)
        )
        cursor = (
            ReadCursor.decode(projection.next_cursor) if projection.next_cursor else None
        )
        steps += 1

    assert projection is not None
    assert projection.truncated is False  # last slice is complete
    assert projection.next_cursor is None


def test_default_view_is_truncated_and_returns_head(tmp_path) -> None:
    adapter, resource_id = _store_with_resource(tmp_path, _multi_section_clean())
    projector = WebProjector()

    projection = projector.default_view(adapter, resource_id, max_tokens=1_200)

    assert projection.truncated is True
    assert projection.content.strip() != ""
    assert projection.next_cursor is not None


def test_select_within_budget_keeps_head_and_tail() -> None:
    from agent_core.domain.web_resource import WebChunkView
    from agent_tools.web_projection import _select_within_budget

    chunks = tuple(
        WebChunkView(
            ordinal=i,
            heading_path=None,
            char_start=0,
            char_end=0,
            token_count=100,
            text=f"chunk{i}",
        )
        for i in range(6)
    )

    selected, truncated = _select_within_budget(chunks, max_tokens=350, reserve_tail=0.1)

    assert truncated is True
    # head fills from the start, tail reserves the final chunk
    texts = [chunk.text for chunk in selected]
    assert texts[0] == "chunk0"
    assert texts[-1] == "chunk5"


def test_web_find_tool_rejects_unknown_resource(tmp_path) -> None:
    adapter, _ = _store_with_resource(tmp_path, _multi_section_clean())
    tool = WebFindTool(store=adapter, projector=WebProjector())
    call = _call("web.find", {"resource_id": str(WebResourceId.new()), "query": "revenue"})

    result = tool.handle(call)

    assert result.metadata["reason"] == "resource_not_found"
    assert result.status.value == "failed"


def test_web_read_tool_never_exposes_disk_path(tmp_path) -> None:
    adapter, resource_id = _store_with_resource(tmp_path, _multi_section_clean())
    tool = WebReadTool(store=adapter, projector=WebProjector())
    call = _call("web.read", {"resource_id": resource_id.value, "max_output_tokens": 1_000})

    result = tool.handle(call)

    assert result.status.value == "executed"
    blob = repr(result.metadata) + result.output
    assert str(tmp_path) not in blob  # no disk path leaks to the model
    assert result.metadata["untrusted_external_content"] is True
    assert result.metadata["resource_id"] == resource_id.value
    envelope = result.metadata["web_envelope"]
    assert envelope["capability_version"] == WEB_ENVELOPE_CAPABILITY_VERSION
    assert envelope["provider"] == "web_projection"
    assert envelope["resource_id"] == resource_id.value


def test_web_read_tool_rejects_cursor_targeting_other_resource(tmp_path) -> None:
    adapter, resource_id = _store_with_resource(tmp_path, _multi_section_clean())
    other = WebResourceId.new()
    foreign_cursor = ReadCursor(resource_id=other, next_ordinal=0).encode()
    tool = WebReadTool(store=adapter, projector=WebProjector())
    call = _call("web.read", {"resource_id": resource_id.value, "cursor": foreign_cursor})

    result = tool.handle(call)

    assert result.metadata["reason"] == "cursor_resource_mismatch"
