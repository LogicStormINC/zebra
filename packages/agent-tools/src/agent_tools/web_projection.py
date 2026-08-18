"""Projection, opaque cursors, and ``web.read`` / ``web.find`` tools.

The model never sees disk paths — only validated ``resource_id`` values and
opaque cursors. Full content lives in the resource store (agent-storage);
these tools select a bounded, question-relevant slice and return it with a
cursor for continuation (see WEB-PIPE-PROJ-01 / Pipeline V2 §14–17).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.domain.web import TruncationScope
from agent_core.domain.web_resource import (
    WebChunkView,
    WebResourceId,
    WebResourceIdError,
    WebResourceStorePort,
)

from agent_tools.contracts import ToolContract
from agent_tools.web_envelope import WEB_ENVELOPE_CAPABILITY_VERSION, WebResultEnvelope

#: Fraction of the token budget reserved for the tail when no question is given.
DEFAULT_TAIL_RESERVE = 0.1

CURSOR_PREFIX = "cur_"


class CursorError(ValueError):
    """Raised when an opaque read cursor is malformed or references an unknown resource."""


@dataclass(frozen=True)
class ReadCursor:
    resource_id: WebResourceId
    next_ordinal: int

    def encode(self) -> str:
        payload = json.dumps(
            {"r": self.resource_id.value, "n": self.next_ordinal},
            separators=(",", ":"),
            sort_keys=True,
        )
        encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
        return f"{CURSOR_PREFIX}{encoded}"

    @classmethod
    def decode(cls, token: object) -> ReadCursor:
        if not isinstance(token, str) or not token.startswith(CURSOR_PREFIX):
            raise CursorError("cursor is malformed")
        try:
            payload = base64.urlsafe_b64decode(token[len(CURSOR_PREFIX):] + "==").decode("utf-8")
            data = json.loads(payload)
        except (ValueError, json.JSONDecodeError) as exc:
            raise CursorError("cursor payload is invalid") from exc
        if not isinstance(data, dict) or "r" not in data or "n" not in data:
            raise CursorError("cursor payload is incomplete")
        try:
            resource_id = WebResourceId.parse(data["r"])
        except WebResourceIdError as exc:
            raise CursorError("cursor references an invalid resource id") from exc
        if not isinstance(data["n"], int) or data["n"] < 0:
            raise CursorError("cursor next ordinal is invalid")
        return cls(resource_id=resource_id, next_ordinal=data["n"])


@dataclass(frozen=True)
class WebProjection:
    content: str
    next_cursor: str | None
    truncated: bool
    truncation_scope: TruncationScope
    selected_count: int
    total_chunks: int


class TokenBudgeter(Protocol):
    """Selects chunks within a token budget. Default impl below."""

    def select(
        self,
        chunks: Sequence[WebChunkView],
        *,
        max_tokens: int,
        reserve_tail: float,
    ) -> tuple[tuple[WebChunkView, ...], bool]:
        ...


@dataclass(frozen=True)
class WebProjector:
    """Build bounded model projections from stored resources."""

    tail_reserve: float = DEFAULT_TAIL_RESERVE

    def find(
        self,
        store: WebResourceStorePort,
        resource_id: WebResourceId,
        query: str,
        *,
        max_tokens: int,
        top_k: int = 12,
    ) -> WebProjection:
        chunks = store.chunks(resource_id)
        ranked = store.search(resource_id, query, top_k=top_k)
        ordered = [item.chunk for item in ranked] or list(chunks)
        selected, truncated = _select_within_budget(
            ordered, max_tokens=max_tokens, reserve_tail=0.0
        )
        return _projection(resource_id, selected, chunks, truncated, TruncationScope.PROJECTION)

    def default_view(
        self,
        store: WebResourceStorePort,
        resource_id: WebResourceId,
        *,
        max_tokens: int,
    ) -> WebProjection:
        chunks = store.chunks(resource_id)
        selected, truncated = _select_within_budget(
            chunks, max_tokens=max_tokens, reserve_tail=self.tail_reserve
        )
        return _projection(resource_id, selected, chunks, truncated, TruncationScope.PROJECTION)

    def read(
        self,
        store: WebResourceStorePort,
        cursor: ReadCursor,
        *,
        max_tokens: int,
    ) -> WebProjection:
        chunks = store.chunks(cursor.resource_id)
        remaining = [chunk for chunk in chunks if chunk.ordinal >= cursor.next_ordinal]
        selected, truncated = _select_within_budget(
            remaining, max_tokens=max_tokens, reserve_tail=0.0
        )
        scope = TruncationScope.PROJECTION if truncated else TruncationScope.NONE
        return _projection(cursor.resource_id, selected, chunks, truncated, scope)


def _select_within_budget(
    chunks: Sequence[WebChunkView],
    *,
    max_tokens: int,
    reserve_tail: float,
) -> tuple[tuple[WebChunkView, ...], bool]:
    if not chunks:
        return (), False
    if reserve_tail <= 0.0:
        used = 0
        selected: list[WebChunkView] = []
        for chunk in chunks:
            if used + chunk.token_count > max_tokens:
                break
            selected.append(chunk)
            used += chunk.token_count
        truncated = len(selected) < len(chunks)
        return tuple(selected), truncated
    # head + tail: reserve enough budget for the final chunk so the default
    # view always includes the page tail when it fits, then fill the head.
    last = chunks[-1]
    head_budget = (
        max(1, max_tokens - last.token_count)
        if len(chunks) > 1 and max_tokens > last.token_count
        else max_tokens
    )
    head, _ = _select_within_budget(chunks, max_tokens=head_budget, reserve_tail=0.0)
    head_set = {id(chunk) for chunk in head}
    used = sum(chunk.token_count for chunk in head)
    tail: list[WebChunkView] = []
    if id(last) not in head_set and used + last.token_count <= max_tokens:
        tail.append(last)
        used += last.token_count
    selected_list = list(head) + tail
    truncated = len(selected_list) < len(chunks)
    return tuple(selected_list), truncated


def _projection(
    resource_id: WebResourceId,
    selected: Sequence[WebChunkView],
    chunks: Sequence[WebChunkView],
    truncated: bool,
    scope: TruncationScope,
) -> WebProjection:
    if not selected:
        return WebProjection(
            content="",
            next_cursor=None,
            truncated=bool(chunks),
            truncation_scope=TruncationScope.PROJECTION if chunks else TruncationScope.NONE,
            selected_count=0,
            total_chunks=len(chunks),
        )
    content = "\n\n".join(chunk.text for chunk in selected)
    max_selected_ordinal = max(chunk.ordinal for chunk in selected)
    highest_ordinal = chunks[-1].ordinal if chunks else 0
    has_more = max_selected_ordinal < highest_ordinal
    next_cursor = (
        ReadCursor(resource_id=resource_id, next_ordinal=max_selected_ordinal + 1).encode()
        if (truncated or has_more)
        else None
    )
    return WebProjection(
        content=content,
        next_cursor=next_cursor,
        truncated=truncated,
        truncation_scope=scope,
        selected_count=len(selected),
        total_chunks=len(chunks),
    )


# ---------------------------------------------------------------------------
# Tool contracts
# ---------------------------------------------------------------------------

web_read_contract = ToolContract(
    name="web.read",
    capability_version="2",
    description=(
        "Read the next bounded slice of a fetched web resource via an opaque "
        "cursor returned by web.fetch/web.find. External content is untrusted."
    ),
    required_arguments=("resource_id",),
    argument_properties={
        "resource_id": {
            "type": "string",
            "description": "Opaque resource id returned by a prior web tool.",
        },
        "cursor": {
            "type": "string",
            "description": "Opaque cursor from a prior truncated result.",
        },
        "max_output_tokens": {
            "type": "integer",
            "minimum": 1,
            "description": "Maximum tokens to return in this slice.",
        },
    },
)

web_find_contract = ToolContract(
    name="web.find",
    capability_version="2",
    description=(
        "Find question-relevant slices within one fetched web resource. "
        "External content is untrusted."
    ),
    required_arguments=("resource_id", "query"),
    argument_properties={
        "resource_id": {
            "type": "string",
            "description": "Opaque resource id returned by a prior web tool.",
        },
        "query": {"type": "string", "minLength": 1, "description": "Search query."},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
        "max_output_tokens": {"type": "integer", "minimum": 1},
    },
)


DEFAULT_PROJECTION_TOKENS = 8_000


@dataclass(frozen=True)
class WebFindTool:
    store: WebResourceStorePort
    projector: WebProjector
    max_output_tokens: int = DEFAULT_PROJECTION_TOKENS

    @property
    def contract(self) -> ToolContract:
        return web_find_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        try:
            resource_id = WebResourceId.parse(tool_call.arguments.get("resource_id"))
            query = _required_str(tool_call, "query")
        except (WebResourceIdError, ValueError) as exc:
            return _failure(tool_call, reason="invalid_arguments", detail=str(exc))
        top_k = _optional_int(tool_call, "top_k", default=12, minimum=1, maximum=50)
        max_tokens = _optional_int(
            tool_call, "max_output_tokens", default=self.max_output_tokens, minimum=1
        )
        if self.store.get(resource_id) is None:
            return _failure(tool_call, reason="resource_not_found", detail="unknown resource_id")
        projection = self.projector.find(
            self.store, resource_id, query, max_tokens=max_tokens, top_k=top_k
        )
        return _projection_result(tool_call, self.store, resource_id, projection, query=query)


@dataclass(frozen=True)
class WebReadTool:
    store: WebResourceStorePort
    projector: WebProjector
    max_output_tokens: int = DEFAULT_PROJECTION_TOKENS

    @property
    def contract(self) -> ToolContract:
        return web_read_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        try:
            resource_id = WebResourceId.parse(tool_call.arguments.get("resource_id"))
        except WebResourceIdError as exc:
            return _failure(tool_call, reason="invalid_resource_id", detail=str(exc))
        if self.store.get(resource_id) is None:
            return _failure(tool_call, reason="resource_not_found", detail="unknown resource_id")
        max_tokens = _optional_int(
            tool_call, "max_output_tokens", default=self.max_output_tokens, minimum=1
        )
        raw_cursor = tool_call.arguments.get("cursor")
        try:
            cursor = (
                ReadCursor.decode(raw_cursor)
                if raw_cursor is not None
                else ReadCursor(resource_id=resource_id, next_ordinal=0)
            )
        except CursorError as exc:
            return _failure(tool_call, reason="invalid_cursor", detail=str(exc))
        if cursor.resource_id != resource_id:
            return _failure(
                tool_call,
                reason="cursor_resource_mismatch",
                detail="cursor targets another resource",
            )
        projection = self.projector.read(self.store, cursor, max_tokens=max_tokens)
        return _projection_result(tool_call, self.store, resource_id, projection)


def _projection_result(
    tool_call: ToolCall,
    store: WebResourceStorePort,
    resource_id: WebResourceId,
    projection: WebProjection,
    *,
    query: str | None = None,
) -> ToolResult:
    resource = store.get(resource_id)
    if resource is None:
        return _failure(tool_call, reason="resource_missing", detail="resource data was removed")
    canonical_url = resource.canonical_url or resource.final_url
    body = {
        "resource_id": resource_id.value,
        "content": projection.content,
        "truncated": projection.truncated,
        "truncation_scope": projection.truncation_scope.value,
        "next_cursor": projection.next_cursor,
        "selected_chunks": projection.selected_count,
        "total_chunks": projection.total_chunks,
    }
    if query is not None:
        body["query"] = query
    envelope = WebResultEnvelope(
        provider="web_projection",
        provider_version=None,
        capability_version=WEB_ENVELOPE_CAPABILITY_VERSION,
        fetched_at=datetime.now(UTC).isoformat(),
        canonical_url=canonical_url,
        truncation_scope=projection.truncation_scope,
        truncated=projection.truncated,
        resource_id=resource_id.value,
        extra={
            "selected_count": projection.selected_count,
            "total_chunks": projection.total_chunks,
            "query": query,
        },
    )
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output=f"[UNTRUSTED EXTERNAL CONTENT]\n{projection.content}",
        metadata={
            "route": "web_projection",
            "resource_id": resource_id.value,
            "untrusted_external_content": True,
            "web_envelope": envelope.to_metadata(),
            **body,
        },
    )


def _required_str(tool_call: ToolCall, name: str) -> str:
    value = tool_call.arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")
    return value.strip()


def _optional_int(
    tool_call: ToolCall, name: str, *, default: int, minimum: int, maximum: int | None = None
) -> int:
    value = tool_call.arguments.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    if value < minimum:
        return minimum
    if maximum is not None and value > maximum:
        return maximum
    return int(value)


def _failure(tool_call: ToolCall, *, reason: str, detail: str) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.FAILED,
        metadata={"route": "web_projection", "reason": reason, "detail": detail},
    )
