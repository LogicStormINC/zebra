from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict
from http.client import HTTPException

from agent_core.domain.web import WebTargetError, parse_web_target
from agent_tools.web_gateway import WebGatewayError
from agent_tools.web_search import (
    MAX_SEARCH_CANDIDATE_CHARS,
    MAX_SEARCH_CANDIDATES,
    MAX_WEB_SEARCH_SNIPPET_CHARS,
    MAX_WEB_SEARCH_TITLE_CHARS,
    MAX_WEB_SEARCH_URL_CHARS,
    WebSearchRequest,
    WebSearchResponse,
    WebSearchResult,
)
from pydantic import TypeAdapter

from agent_runtime.public_dns import PublicAddressBlocked
from agent_runtime.search_egress import search_network_options
from agent_runtime.search_health import require_complete_search
from agent_runtime.web_gateway import (
    _native_network_call,
    _NoRedirectHandler,
    _read_bounded_body,
)

JSON_CONTENT_TYPE = "application/json"
MAX_OUTPUT_CHARS = MAX_SEARCH_CANDIDATE_CHARS


class LocalWebSearchTransport:
    """Credential-free bounded SearXNG JSON adapter."""

    def __init__(
        self,
        *,
        use_system_proxy: bool = False,
        network_cancellation_check: Callable[[], None] | None = None,
        trusted_search_endpoint: str | None = None,
    ) -> None:
        self._use_system_proxy = use_system_proxy
        self._network_cancellation_check = network_cancellation_check
        self._trusted_search_endpoint = trusted_search_endpoint

    def execute(self, request: WebSearchRequest) -> WebSearchResponse:
        if self._network_cancellation_check is not None:
            return TypeAdapter(WebSearchResponse).validate_python(
                _native_network_call(
                    "search",
                    asdict(request),
                    self._network_cancellation_check,
                    timeout=request.timeout_seconds,
                    use_system_proxy=self._use_system_proxy,
                    max_output_bytes=request.max_bytes * 6 + 65536,
                    trusted_search_endpoint=self._trusted_search_endpoint,
                )
            )
        proxies, https_handler = search_network_options(
            request.endpoint.url,
            self._trusted_search_endpoint,
            use_system_proxy=self._use_system_proxy,
        )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies),
            _NoRedirectHandler(),
            *((https_handler,) if https_handler is not None else ()),
        )
        outbound = urllib.request.Request(
            _search_url(request),
            headers={
                "Accept": JSON_CONTENT_TYPE,
                "User-Agent": "Zebra-Agent-Web-Search/1.0",
            },
            method="GET",
        )
        try:
            with opener.open(outbound, timeout=request.timeout_seconds) as response:
                if response.status == 206:
                    raise WebGatewayError(
                        "search source query is incomplete", reason="search_incomplete"
                    )
                content_type = response.headers.get("Content-Type", "").partition(";")[0]
                if content_type.strip().lower() != JSON_CONTENT_TYPE:
                    raise WebGatewayError(
                        "search response content type is not application/json",
                        reason="unsupported_content_type",
                    )
                body = _read_bounded_body(response, request.max_bytes)
                return _normalize_response(body, request, len(body))
        except WebGatewayError:
            raise
        except urllib.error.HTTPError as exc:
            reason = "redirect_blocked" if 300 <= exc.code < 400 else "http_error"
            exc.close()
            raise WebGatewayError(f"search gateway HTTP error: {exc.code}", reason=reason) from exc
        except HTTPException as exc:
            raise WebGatewayError(
                "search response body is incomplete", reason="response_incomplete"
            ) from exc
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            reason = (
                "private_network_blocked"
                if isinstance(getattr(exc, "reason", exc), PublicAddressBlocked)
                else "gateway_unavailable"
            )
            raise WebGatewayError(f"search gateway request failed: {exc}", reason=reason) from exc


def _search_url(request: WebSearchRequest) -> str:
    separator = "&" if urllib.parse.urlsplit(request.endpoint.url).query else "?"
    query = urllib.parse.urlencode({"q": request.query, "format": "json", "limit": request.limit})
    return f"{request.endpoint.url}{separator}{query}"


def _normalize_response(
    body: bytes,
    request: WebSearchRequest,
    byte_count: int,
) -> WebSearchResponse:
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise WebGatewayError(
            "search response has an invalid JSON shape", reason="invalid_response"
        )
    require_complete_search(payload)
    normalized: list[WebSearchResult] = []
    seen_urls: set[str] = set()
    output_chars = 0
    raw_results = payload["results"]
    truncated = len(raw_results) > request.limit
    candidates_truncated = False
    for item in raw_results:
        if len(normalized) >= MAX_SEARCH_CANDIDATES:
            candidates_truncated = True
            break
        result = _normalize_result(item)
        if result is None or result.url in seen_urls:
            truncated = True
            continue
        result_chars = len(result.title) + len(result.url) + len(result.snippet)
        if output_chars + result_chars > MAX_OUTPUT_CHARS:
            truncated = True
            candidates_truncated = True
            break
        normalized.append(result)
        seen_urls.add(result.url)
        output_chars += result_chars
    return WebSearchResponse(
        results=tuple(normalized[:request.limit]),
        candidates=tuple(normalized),
        candidates_truncated=candidates_truncated,
        provider="searxng",
        byte_count=byte_count,
        truncated=truncated,
        metadata={"transport": "local_https", "redirects_followed": 0},
    )


def _normalize_result(value: object) -> WebSearchResult | None:
    if not isinstance(value, dict):
        return None
    raw_url = value.get("url")
    if not isinstance(raw_url, str):
        return None
    try:
        target = parse_web_target(urllib.parse.urldefrag(raw_url).url)
    except WebTargetError:
        return None
    if len(target.url) > MAX_WEB_SEARCH_URL_CHARS:
        return None
    title = _bounded_text(value.get("title"), MAX_WEB_SEARCH_TITLE_CHARS) or target.hostname
    snippet = _bounded_text(value.get("content"), MAX_WEB_SEARCH_SNIPPET_CHARS)
    return WebSearchResult(title=title, url=target.url, snippet=snippet)


def _bounded_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]
