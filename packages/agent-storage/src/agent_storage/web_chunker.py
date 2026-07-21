"""Chunking for stored web content.

Splits cleaned Markdown into bounded chunks that prefer heading and paragraph
boundaries, keep tables/code blocks intact where possible, and carry a heading
path + char span so the projector can re-order by original position and
``web.read`` can resume via cursor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass(frozen=True)
class StoredWebChunk:
    ordinal: int
    heading_path: str | None
    char_start: int
    char_end: int
    token_count: int
    text: str

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("chunk ordinal must not be negative")
        if self.char_start < 0 or self.char_end < self.char_start:
            raise ValueError("chunk char span is invalid")
        if self.token_count < 0:
            raise ValueError("chunk token_count must not be negative")


@dataclass(frozen=True)
class ChunkingLimits:
    target_tokens: int = 1_000
    max_tokens: int = 1_200
    overlap_tokens: int = 120

    def __post_init__(self) -> None:
        if self.target_tokens <= 0 or self.max_tokens <= 0:
            raise ValueError("token limits must be positive")
        if self.target_tokens > self.max_tokens:
            raise ValueError("target_tokens must not exceed max_tokens")
        if self.overlap_tokens < 0:
            raise ValueError("overlap_tokens must not be negative")


def estimate_tokens(text: str) -> int:
    """Crude deterministic token proxy (whitespace token count, floor 1).

    Good enough for chunk sizing; the projector enforces the real model-byte
    budget separately.
    """
    return max(1, len(text.split()))


def chunk_clean_text(
    text: str, *, limits: ChunkingLimits | None = None
) -> tuple[StoredWebChunk, ...]:
    """Split ``text`` into ``StoredWebChunk``s with heading paths and char spans."""
    if not text.strip():
        return ()
    limits = limits or ChunkingLimits()
    blocks = _annotated_blocks(text)
    chunks: list[StoredWebChunk] = []
    # Each buffered item: (start, end, segment, heading_path_at_block)
    buffer: list[tuple[int, int, str, str | None]] = []
    buffer_tokens = 0
    ordinal = 0

    def flush() -> None:
        nonlocal buffer, buffer_tokens, ordinal
        if not buffer:
            return
        start = buffer[0][0]
        end = buffer[-1][1]
        segment_text = text[start:end]
        chunks.append(
            StoredWebChunk(
                ordinal=ordinal,
                heading_path=buffer[0][3],
                char_start=start,
                char_end=end,
                token_count=estimate_tokens(segment_text),
                text=segment_text,
            )
        )
        ordinal += 1
        # overlap: keep trailing blocks under overlap budget
        kept: list[tuple[int, int, str, str | None]] = []
        kept_tokens = 0
        for item in reversed(buffer):
            seg_tokens = estimate_tokens(item[2])
            if kept and kept_tokens + seg_tokens > limits.overlap_tokens:
                break
            kept.append(item)
            kept_tokens += seg_tokens
        kept.reverse()
        buffer = list(kept)
        buffer_tokens = sum(estimate_tokens(item[2]) for item in buffer)

    for start, end, segment, heading_path in blocks:
        seg_tokens = estimate_tokens(segment)
        if buffer and buffer_tokens + seg_tokens > limits.max_tokens:
            flush()
        buffer.append((start, end, segment, heading_path))
        buffer_tokens += seg_tokens
        if buffer_tokens >= limits.target_tokens:
            flush()
    flush()
    return tuple(chunks)


def _annotated_blocks(text: str) -> list[tuple[int, int, str, str | None]]:
    """Paragraph/heading blocks with the heading-path snapshot captured when
    each block was encountered, so a chunk's heading path reflects its first
    block rather than whatever heading was active at flush time."""
    annotated: list[tuple[int, int, str, str | None]] = []
    heading_stack: list[str] = []
    for start, end, segment in _split_blocks(text):
        heading = _heading_of(segment)
        if heading is not None:
            level, title = heading
            heading_stack = heading_stack[: max(0, level - 1)]
            heading_stack.append(title)
        annotated.append((start, end, segment, " / ".join(heading_stack) or None))
    return annotated


def _split_blocks(text: str) -> list[tuple[int, int, str]]:
    """Split into paragraph/heading/code blocks, each a (start, end, segment)
    where start/end are absolute char offsets in ``text``."""
    blocks: list[tuple[int, int, str]] = []
    cursor = 0
    for raw_block in re.split(r"\n{2,}", text):
        anchor = text.find(raw_block, cursor)
        if anchor == -1:
            anchor = cursor
        end = anchor + len(raw_block)
        segment = text[anchor:end]
        if segment.strip():
            blocks.append((anchor, end, segment))
        cursor = end
    return blocks


def _heading_of(segment: str) -> tuple[int, str] | None:
    first_line = segment.lstrip().split("\n", 1)[0]
    match = _HEADING_RE.match(first_line)
    if match is None:
        return None
    return len(match.group(1)), match.group(2).strip()
