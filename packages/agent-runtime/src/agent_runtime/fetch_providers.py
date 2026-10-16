"""Working FetchProvider backed by the existing local urllib HTTP transport.

Used as the default fetch backend so ``web.fetch`` is functional without the
optional Crawl4AI package (which provides browser/SPA rendering via Setup
Phase). Reuses ``LocalWebGatewayTransport`` (no-redirect, proxy discipline,
public-address preflight, HTML cleaning via ``project_web_text``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent_core.domain.web import WebTargetError, parse_web_target
from agent_tools.web_crawl import FetchProviderError, FetchRequest, FetchResult
from agent_tools.web_gateway import (
    DEFAULT_WEB_MAX_BYTES,
    DEFAULT_WEB_MAX_OUTPUT_BYTES,
    WebGatewayError,
    WebGatewayRequest,
)

from agent_runtime.web_gateway import LocalWebGatewayTransport


@dataclass(frozen=True)
class LocalHttpFetchProvider:
    use_system_proxy: bool = False
    max_bytes: int = DEFAULT_WEB_MAX_BYTES
    network_cancellation_check: Callable[[], None] | None = None

    @property
    def name(self) -> str:
        return "local_http"

    @property
    def available(self) -> bool:
        return True

    def fetch(self, request: FetchRequest) -> FetchResult:
        transport = LocalWebGatewayTransport(
            use_system_proxy=self.use_system_proxy,
            network_cancellation_check=self.network_cancellation_check,
        )
        try:
            target = parse_web_target(request.url)
        except WebTargetError as exc:
            raise FetchProviderError(str(exc), reason="invalid_web_target") from exc
        try:
            response = transport.execute(
                WebGatewayRequest(
                    tool_call_id="fetch",
                    target=target,
                    max_bytes=self.max_bytes,
                    max_output_bytes=DEFAULT_WEB_MAX_OUTPUT_BYTES,
                )
            )
        except WebGatewayError as exc:
            raise FetchProviderError(str(exc), reason=exc.reason) from exc
        refs = response.metadata.get("evidence_refs", [])
        return FetchResult(
            evidence_refs=tuple(ref for ref in refs if isinstance(ref, str))
            if isinstance(refs, list) else (),
            requested_url=request.url,
            final_url=target.url,
            clean_markdown=response.text,
            fetch_mode="http",
            complete=response.status_code != 206
            and response.metadata.get("output_truncated") is False,
            truncation_reason=(
                "partial_content"
                if response.status_code == 206
                else "source_output_limit"
                if response.metadata.get("output_truncated") is True
                else None
            ),
            content_type=response.content_type,
            wire_bytes=response.byte_count,
            decoded_bytes=response.byte_count,
        )
