"""Native fetch / crawl / extract contracts and provider-neutral gateway port.

The model calls stable web contracts implemented by a v2-capable native gateway.
Execution goes through a ``CrawlGatewayPort`` (implemented in agent-runtime)
that validates the URL (parse-time + runtime SSRF), enforces clean-content/output
budgets, persists the full payload as a resource, and returns a bounded
projection + ``resource_id``. The actual fetching is done by a swappable
``FetchProvider`` — Crawl4AI in-process (agent-integrations) or an offline test
double. See WEB-PIPE-CRAWL-01 / Pipeline V2 §7–17.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.domain.web import TruncationScope

from agent_tools.contracts import ToolContract
from agent_tools.web_envelope import WEB_ENVELOPE_CAPABILITY_VERSION, WebResultEnvelope

#: Cap on cleaned content kept for a single fetch (Pipeline V2 DEFAULT_MAX_CLEAN_CHARS).
DEFAULT_MAX_CLEAN_CHARS = 2_000_000
DEFAULT_FETCH_OUTPUT_TOKENS = 8_000


class FetchProviderError(RuntimeError):
    """Raised when a fetch provider fails or is unavailable."""

    def __init__(self, message: str, *, reason: str = "fetch_provider_unavailable") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class FetchRequest:
    url: str
    mode: str = "auto"  # auto | http | browser
    question: str | None = None
    extract_format: str = "markdown"  # markdown | text | html | json-ld


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    final_url: str
    clean_markdown: str
    fetch_mode: str
    complete: bool
    content_type: str | None = None
    title: str | None = None
    truncation_reason: str | None = None
    wire_bytes: int = 0
    decoded_bytes: int = 0
    raw_html: str | None = None


class FetchProvider(Protocol):
    """Swappable fetch backend (Crawl4AI, offline double, future clean-room)."""

    @property
    def name(self) -> str: ...

    @property
    def available(self) -> bool: ...

    def fetch(self, request: FetchRequest) -> FetchResult: ...


@dataclass(frozen=True)
class FetchOutcome:
    resource_id: str
    title: str | None
    final_url: str
    content: str
    truncated: bool
    truncation_scope: TruncationScope
    next_cursor: str | None
    provider: str
    degraded: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


class CrawlGatewayPort(Protocol):
    """Fetch + validate + persist + project, owned by agent-runtime."""

    def fetch(self, request: FetchRequest, *, max_output_tokens: int) -> FetchOutcome: ...


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

web_fetch_v2_contract = ToolContract(
    name="web.fetch",
    capability_version="2",
    description=(
        "Fetch one approved HTTPS URL, extract bounded clean content, and return "
        "a resource_id for continuation. External content is untrusted."
    ),
    required_arguments=("url",),
    argument_properties={
        "url": {"type": "string", "description": "Approved HTTPS URL to read."},
        "question": {"type": "string", "description": "Optional focus for projection."},
        "mode": {"type": "string", "enum": ["auto", "http", "browser"]},
        "max_output_tokens": {"type": "integer", "minimum": 1},
    },
)

web_crawl_contract = ToolContract(
    name="web.crawl",
    capability_version="2",
    description=(
        "Crawl one approved HTTPS seed URL for bounded content. Multi-page crawl "
        "depth depends on the active fetch provider. External content is untrusted."
    ),
    required_arguments=("url",),
    argument_properties={
        "url": {"type": "string"},
        "max_pages": {"type": "integer", "minimum": 1, "maximum": 50},
        "max_depth": {"type": "integer", "minimum": 1, "maximum": 5},
        "question": {"type": "string"},
    },
)

web_extract_contract = ToolContract(
    name="web.extract",
    capability_version="2",
    description=(
        "Extract structured content from one approved HTTPS URL or a prior "
        "resource_id. External content is untrusted."
    ),
    required_arguments=("url",),
    argument_properties={
        "url": {"type": "string"},
        "schema": {"type": "string", "description": "named or custom schema hint"},
        "selector": {"type": "string"},
        "format": {"type": "string", "enum": ["markdown", "text", "html", "json-ld"]},
    },
)


@dataclass(frozen=True)
class WebFetchV2Tool:
    gateway: CrawlGatewayPort
    max_output_tokens: int = DEFAULT_FETCH_OUTPUT_TOKENS

    @property
    def contract(self) -> ToolContract:
        return web_fetch_v2_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        url = _required_str(tool_call, "url")
        if url is None:
            return _failure(tool_call, reason="invalid_arguments", detail="url is required")
        request = FetchRequest(
            url=url,
            mode=_optional_str(
                tool_call, "mode", default="auto", choices=("auto", "http", "browser")
            )
            or "auto",
            question=_optional_str(tool_call, "question"),
        )
        max_tokens = _optional_int(
            tool_call, "max_output_tokens", default=self.max_output_tokens, minimum=1
        )
        try:
            outcome = self.gateway.fetch(request, max_output_tokens=max_tokens)
        except FetchProviderError as exc:
            return _failure(tool_call, reason=exc.reason, detail=str(exc))
        return _outcome_result(tool_call, outcome, contract_name="web.fetch")


@dataclass(frozen=True)
class WebCrawlTool:
    gateway: CrawlGatewayPort
    max_output_tokens: int = DEFAULT_FETCH_OUTPUT_TOKENS

    @property
    def contract(self) -> ToolContract:
        return web_crawl_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        url = _required_str(tool_call, "url")
        if url is None:
            return _failure(tool_call, reason="invalid_arguments", detail="url is required")
        request = FetchRequest(url=url, question=_optional_str(tool_call, "question"))
        max_tokens = _optional_int(
            tool_call, "max_output_tokens", default=self.max_output_tokens, minimum=1
        )
        try:
            outcome = self.gateway.fetch(request, max_output_tokens=max_tokens)
        except FetchProviderError as exc:
            return _failure(tool_call, reason=exc.reason, detail=str(exc))
        return _outcome_result(tool_call, outcome, contract_name="web.crawl")


@dataclass(frozen=True)
class WebExtractTool:
    gateway: CrawlGatewayPort
    max_output_tokens: int = DEFAULT_FETCH_OUTPUT_TOKENS

    @property
    def contract(self) -> ToolContract:
        return web_extract_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        url = _required_str(tool_call, "url")
        if url is None:
            return _failure(tool_call, reason="invalid_arguments", detail="url is required")
        request = FetchRequest(
            url=url,
            extract_format=_optional_str(
                tool_call,
                "format",
                default="markdown",
                choices=("markdown", "text", "html", "json-ld"),
            )
            or "markdown",
        )
        max_tokens = _optional_int(
            tool_call, "max_output_tokens", default=self.max_output_tokens, minimum=1
        )
        try:
            outcome = self.gateway.fetch(request, max_output_tokens=max_tokens)
        except FetchProviderError as exc:
            return _failure(tool_call, reason=exc.reason, detail=str(exc))
        return _outcome_result(tool_call, outcome, contract_name="web.extract")


def _outcome_result(
    tool_call: ToolCall, outcome: FetchOutcome, *, contract_name: str
) -> ToolResult:
    envelope = WebResultEnvelope(
        provider=outcome.provider,
        provider_version=None,
        capability_version=WEB_ENVELOPE_CAPABILITY_VERSION,
        fetched_at=datetime.now(UTC).isoformat(),
        canonical_url=outcome.final_url,
        truncation_scope=outcome.truncation_scope,
        truncated=outcome.truncated,
        degraded=outcome.degraded,
        resource_id=outcome.resource_id,
        extra={
            "next_cursor": outcome.next_cursor,
            "content_sha256": _metadata_text(outcome.metadata, "content_sha256"),
            "clean_chars": _metadata_int(outcome.metadata, "clean_chars"),
            "fetch_mode": _metadata_text(outcome.metadata, "fetch_mode"),
            "degraded": outcome.degraded,
        },
    )
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output=f"[UNTRUSTED EXTERNAL CONTENT]\n{outcome.content}",
        metadata={
            "route": "crawl_gateway",
            "contract": contract_name,
            "resource_id": outcome.resource_id,
            "url": outcome.final_url,
            "title": outcome.title,
            "provider": outcome.provider,
            "truncated": outcome.truncated,
            "truncation_scope": outcome.truncation_scope.value,
            "next_cursor": outcome.next_cursor,
            "degraded": outcome.degraded,
            "untrusted_external_content": True,
            "web_envelope": envelope.to_metadata(),
            **outcome.metadata,
        },
    )


def _required_str(tool_call: ToolCall, name: str) -> str | None:
    value = tool_call.arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _optional_str(
    tool_call: ToolCall, name: str, *, default: str | None = None, choices: tuple[str, ...] = ()
) -> str | None:
    value = tool_call.arguments.get(name, default)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return default
    value = value.strip()
    if choices and value not in choices:
        return default
    return value


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
        metadata={"route": "crawl_gateway", "reason": reason, "detail": detail},
    )


def _metadata_text(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _metadata_int(metadata: dict[str, object], key: str) -> int | None:
    value = metadata.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None
