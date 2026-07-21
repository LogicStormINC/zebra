from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from agent_core.domain.web_resource import WebResourceId
from agent_storage.web_chunker import ChunkingLimits, chunk_clean_text, estimate_tokens
from agent_storage.web_resource import (
    ResourceStatus,
    SQLiteWebResourceStore,
    StoredWebResource,
    utc_now_iso,
)


def _resource(
    *,
    content_sha256: str,
    resource_id: str | None = None,
    clean_text: str = "body",
) -> StoredWebResource:
    return StoredWebResource(
        resource_id=resource_id or str(WebResourceId.new()),
        requested_url="https://example.com/page",
        final_url="https://example.com/page",
        content_sha256=content_sha256,
        created_at=utc_now_iso(),
        fetch_mode="http",
        resource_status=ResourceStatus.COMPLETE,
        wire_bytes=len(clean_text.encode("utf-8")),
        decoded_bytes=len(clean_text.encode("utf-8")),
        clean_chars=len(clean_text),
    )


def test_chunker_assigns_heading_paths_and_char_spans() -> None:
    text = (
        "# Title\n\n"
        + "alpha beta gamma " * 200
        + "\n\n## Section\n\n"
        + "delta epsilon zeta " * 200
    )

    chunks = chunk_clean_text(text)

    assert len(chunks) >= 2
    assert chunks[0].heading_path == "Title"
    assert all(c.char_start < c.char_end for c in chunks)
    # every chunk text is a substring of the source
    for chunk in chunks:
        assert text[chunk.char_start:chunk.char_end] == chunk.text


def test_chunker_handles_empty_text() -> None:
    assert chunk_clean_text("") == ()
    assert chunk_clean_text("   \n\n  ") == ()


def test_store_round_trips_resource_and_chunks(tmp_path) -> None:
    store = SQLiteWebResourceStore(tmp_path / "web.db", tmp_path / "cache")
    clean = "# Heading\n\nfirst paragraph about revenue.\n\nsecond about margin."
    sha = sha256(clean.encode("utf-8")).hexdigest()
    resource = _resource(content_sha256=sha, clean_text=clean)
    chunks = chunk_clean_text(clean)
    resource_id = store.save(resource=resource, chunks=chunks, clean_text=clean)

    fetched = store.get(resource_id)
    assert fetched is not None
    assert fetched.title is None
    assert fetched.resource_status is ResourceStatus.COMPLETE
    assert store.chunks(resource_id) == chunks
    assert store.clean_text(resource_id) == clean


def test_store_dedups_by_content_hash(tmp_path) -> None:
    store = SQLiteWebResourceStore(tmp_path / "web.db", tmp_path / "cache")
    clean = "duplicate payload"
    sha = sha256(clean.encode("utf-8")).hexdigest()
    first = _resource(content_sha256=sha, clean_text=clean)
    second = _resource(content_sha256=sha, clean_text=clean)

    first_id = store.save(resource=first, chunks=(), clean_text=clean)
    second_id = store.save(resource=second, chunks=(), clean_text=clean)

    assert first_id == second_id  # dedup returns the original id


def test_store_fts_search_returns_matching_chunk(tmp_path) -> None:
    store = SQLiteWebResourceStore(tmp_path / "web.db", tmp_path / "cache")
    clean = (
        "# Financials\n\n"
        "Quarterly revenue grew 20 percent year over year.\n\n"
        "Operating margin expanded to 18 percent."
    )
    sha = sha256(clean.encode("utf-8")).hexdigest()
    resource_id = store.save(
        resource=_resource(content_sha256=sha, clean_text=clean),
        chunks=chunk_clean_text(clean),
        clean_text=clean,
    )

    ranked = store.search(resource_id, "revenue", top_k=5)

    assert ranked
    assert any("revenue" in r.chunk.text.lower() for r in ranked)
    # an unrelated query returns nothing
    assert store.search(resource_id, "nonexistentterm", top_k=5) == ()


def test_store_is_stale_respects_expires_at(tmp_path) -> None:
    store = SQLiteWebResourceStore(tmp_path / "web.db", tmp_path / "cache")
    clean = "expiring payload"
    sha = sha256(clean.encode("utf-8")).hexdigest()
    now = datetime.now(UTC)
    resource = StoredWebResource(
        resource_id=str(WebResourceId.new()),
        requested_url="https://example.com/x",
        final_url="https://example.com/x",
        content_sha256=sha,
        created_at=utc_now_iso(),
        fetch_mode="http",
        resource_status=ResourceStatus.COMPLETE,
        wire_bytes=16,
        decoded_bytes=16,
        clean_chars=16,
        expires_at=(now - timedelta(minutes=1)).isoformat(),
    )
    resource_id = store.save(resource=resource, chunks=(), clean_text=clean)

    assert store.is_stale(resource_id, now=now) is True
    assert store.is_stale(resource_id, now=now - timedelta(hours=1)) is False


def test_chunking_limits_validate() -> None:
    with pytest.raises(ValueError):
        ChunkingLimits(target_tokens=10, max_tokens=5)
    with pytest.raises(ValueError):
        ChunkingLimits(target_tokens=0)


def test_estimate_tokens_floors_to_one() -> None:
    assert estimate_tokens("   ") == 1
    assert estimate_tokens("one two three") == 3
