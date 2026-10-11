from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall
from agent_core.domain.web import TruncationScope
from agent_core.domain.web_resource import WebChunkView, WebResourceId, WebResourceView
from agent_storage.web_chunker import chunk_clean_text
from agent_storage.web_resource import (
    ResourceStatus,
    SQLiteWebResourceStore,
    StoredWebResource,
    WebResourceStoreAdapter,
)
from agent_tools.web_envelope import WebResultEnvelope
from agent_tools.web_projection import WebFindTool, WebProjector, WebReadTool


def source(
    tmp_path: Path, status: ResourceStatus, clean: str
) -> tuple[WebResourceStoreAdapter, WebResourceId]:
    store = SQLiteWebResourceStore(tmp_path / "isolated-web.sqlite", tmp_path / "isolated-cache")
    resource_id = store.save(
        resource=StoredWebResource(
            resource_id=WebResourceId.new().value,
            requested_url="https://source.example/evidence",
            final_url="https://source.example/evidence",
            content_sha256=sha256(clean.encode()).hexdigest(),
            created_at=datetime.now(UTC).isoformat(),
            fetch_mode="http",
            resource_status=status,
            wire_bytes=len(clean.encode()),
            decoded_bytes=len(clean.encode()),
            clean_chars=len(clean),
        ),
        chunks=chunk_clean_text(clean),
        clean_text=clean,
    )
    return WebResourceStoreAdapter(store), resource_id


def call(name: str, resource_id: WebResourceId, **extra: object) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        created_at=datetime.now(UTC),
        arguments={"resource_id": resource_id.value, "query": "evidence", **extra},
    )


@pytest.mark.parametrize("name", ["web.read", "web.find"])
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("projection_truncated", [False, True])
def test_source_partial_and_projection_budget_are_independent(
    tmp_path: Path,
    name: str,
    partial: bool,
    projection_truncated: bool,
) -> None:
    adapter, resource_id = source(
        tmp_path,
        ResourceStatus.PARTIAL if partial else ResourceStatus.COMPLETE,
        "# Evidence\n\n" + "evidence " * 100,
    )
    tool = (
        WebReadTool(adapter, WebProjector())
        if name == "web.read"
        else WebFindTool(adapter, WebProjector())
    )
    result = tool.handle(
        call(name, resource_id, max_output_tokens=1 if projection_truncated else 8000)
    )
    assert result.status.value == "executed"
    envelope = result.metadata["web_envelope"]
    for metadata in (result.metadata, envelope):
        assert metadata["source_truncated"] is partial
        assert metadata["projection_truncated"] is projection_truncated
        assert metadata["truncated"] is (partial or projection_truncated)
        assert metadata["degraded"] is partial
        assert metadata["untrusted_external_content"] is True
        assert metadata["truncation_scope"] == (
            "projection" if projection_truncated else "source" if partial else "none"
        )
    assert (
        "evidence" in result.output
        if not projection_truncated
        else result.metadata["selected_chunks"] == 0
    )
    assert str(tmp_path) not in str(result.metadata)


@pytest.mark.parametrize("name", ["web.read", "web.find"])
def test_failed_source_cannot_be_promoted_to_success(
    tmp_path: Path, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, resource_id = source(tmp_path, ResourceStatus.FAILED, "private failed source")

    def forbidden_body(_key: WebResourceId) -> tuple[WebChunkView, ...]:
        pytest.fail("failed source must be rejected before reading its body")

    monkeypatch.setattr(adapter, "chunks", forbidden_body)
    tool = (
        WebReadTool(adapter, WebProjector())
        if name == "web.read"
        else WebFindTool(adapter, WebProjector())
    )
    result = tool.handle(call(name, resource_id))
    assert result.status.value == "failed" and result.metadata["reason"] == "resource_unavailable"
    assert not result.output and "web_envelope" not in result.metadata


def test_partial_source_last_page_never_claims_full_source_or_invents_cursor(
    tmp_path: Path,
) -> None:
    clean = "\n\n".join(f"# Section {i}\n\n" + "evidence " * 200 for i in range(3))
    adapter, resource_id = source(tmp_path, ResourceStatus.PARTIAL, clean)
    tool = WebReadTool(adapter, WebProjector())
    cursor: str | None = None
    for _ in range(20):
        result = tool.handle(call("web.read", resource_id, cursor=cursor, max_output_tokens=800))
        assert result.status.value == "executed" and result.metadata["source_truncated"] is True
        cursor = result.metadata["next_cursor"]
        if cursor is None:
            break
    else:
        pytest.fail("source partial must not fabricate an endless projection cursor")
    assert result.metadata["truncated"] is True
    assert result.metadata["projection_truncated"] is False
    assert result.metadata["web_envelope"]["degraded"] is True


@pytest.mark.parametrize("change", ["unknown_status", "foreign_identity"])
@pytest.mark.parametrize("name", ["web.read", "web.find"])
def test_invalid_source_header_fails_closed(tmp_path: Path, change: str, name: str) -> None:
    adapter, resource_id = source(tmp_path, ResourceStatus.COMPLETE, "evidence")
    original_get = adapter.get

    class InvalidAdapter(WebResourceStoreAdapter):
        def get(self, key: WebResourceId) -> WebResourceView | None:
            resource = original_get(key)
            assert resource is not None
            return (
                replace(resource, resource_status="unknown")
                if change == "unknown_status"
                else replace(resource, resource_id=WebResourceId.new().value)
            )

        def chunks(self, key: WebResourceId) -> tuple[WebChunkView, ...]:
            pytest.fail("invalid source header must be rejected before body reads")

    invalid = InvalidAdapter(adapter._store)
    tool = (
        WebReadTool(invalid, WebProjector())
        if name == "web.read"
        else WebFindTool(invalid, WebProjector())
    )
    result = tool.handle(call(name, resource_id))
    assert result.status.value == "failed" and not result.output
    assert result.metadata["reason"] == (
        "invalid_resource_status" if change == "unknown_status" else "resource_identity_mismatch"
    )


@pytest.mark.parametrize("name", ["web.read", "web.find"])
@pytest.mark.parametrize(
    "change,reason",
    [
        ("failed", "resource_unavailable"),
        ("unknown", "invalid_resource_status"),
        ("foreign", "resource_identity_mismatch"),
        ("missing", "resource_missing"),
        ("partial", None),
    ],
)
def test_header_is_revalidated_before_releasing_projection(
    tmp_path: Path, name: str, change: str, reason: str | None
) -> None:
    adapter, resource_id = source(tmp_path, ResourceStatus.COMPLETE, "evidence")
    original_get = adapter.get
    reads: list[str] = []

    class ChangingAdapter(WebResourceStoreAdapter):
        def get(self, key: WebResourceId) -> WebResourceView | None:
            resource = original_get(key)
            assert resource is not None
            reads.append("header")
            if len(reads) == 1:
                return resource
            if change == "missing":
                return None
            return (
                replace(resource, resource_id=WebResourceId.new().value)
                if change == "foreign"
                else replace(resource, resource_status=change)
            )

        def chunks(self, key: WebResourceId) -> tuple[WebChunkView, ...]:
            reads.append("body")
            return super().chunks(key)

    changing = ChangingAdapter(adapter._store)
    tool = (
        WebReadTool(changing, WebProjector())
        if name == "web.read"
        else WebFindTool(changing, WebProjector())
    )
    result = tool.handle(call(name, resource_id))
    assert reads == ["header", "body", "header"]
    if reason is not None:
        assert result.status.value == "failed" and not result.output
        assert result.metadata["reason"] == reason
        assert "web_envelope" not in result.metadata
    else:
        assert result.status.value == "executed"
        for metadata in (result.metadata, result.metadata["web_envelope"]):
            assert metadata["source_truncated"] is True
            assert metadata["projection_truncated"] is False
            assert metadata["truncated"] is True and metadata["degraded"] is True
            assert metadata["truncation_scope"] == "source"


@pytest.mark.parametrize(
    "source_partial,projection_partial",
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_envelope_preserves_both_truncation_dimensions(
    source_partial: bool, projection_partial: bool
) -> None:
    envelope = WebResultEnvelope(
        provider="native",
        capability_version="2",
        fetched_at=datetime.now(UTC).isoformat(),
        canonical_url="https://source.example/evidence",
        truncated=source_partial or projection_partial,
        truncation_scope=TruncationScope.PROJECTION
        if projection_partial
        else TruncationScope.SOURCE
        if source_partial
        else TruncationScope.NONE,
        source_truncated=source_partial,
        projection_truncated=projection_partial,
        degraded=source_partial,
    )
    metadata = envelope.to_metadata()
    assert metadata["source_truncated"] is source_partial
    assert metadata["projection_truncated"] is projection_partial
    assert metadata["untrusted_external_content"] is True


def test_envelope_rejects_source_partial_downgrade() -> None:
    with pytest.raises(ValueError):
        WebResultEnvelope(
            provider="native",
            capability_version="2",
            fetched_at=datetime.now(UTC).isoformat(),
            canonical_url="https://source.example/evidence",
            truncated=False,
            truncation_scope=TruncationScope.NONE,
            source_truncated=True,
            projection_truncated=False,
            degraded=False,
        )
