"""Working FetchProvider backed by the existing local urllib HTTP transport.

Used as the default fetch backend so ``web.fetch`` is functional without the
optional Crawl4AI package (which provides browser/SPA rendering via Setup
Phase). Reuses ``LocalWebGatewayTransport`` (no-redirect, proxy discipline,
public-address preflight, HTML cleaning via ``project_web_text``).
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_core.domain.web import parse_web_target
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

    @property
    def name(self) -> str:
        return "local_http"

    @property
    def available(self) -> bool:
        return True

    def fetch(self, request: FetchRequest) -> FetchResult:
        transport = LocalWebGatewayTransport(use_system_proxy=self.use_system_proxy)
        try:
            target = parse_web_target(request.url)
        except Exception as exc:  # WebTargetError
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
        return FetchResult(
            requested_url=request.url,
            final_url=target.url,
            clean_markdown=response.text,
            fetch_mode="http",
            complete=True,
            content_type=response.content_type,
            wire_bytes=response.byte_count,
            decoded_bytes=response.byte_count,
        )
