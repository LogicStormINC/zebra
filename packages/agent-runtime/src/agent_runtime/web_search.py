from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from agent_core.domain.web import WebTargetError, parse_web_target
from agent_tools.web_gateway import WebGatewayError
from agent_tools.web_search import (
    MAX_WEB_SEARCH_SNIPPET_CHARS,
    MAX_WEB_SEARCH_TITLE_CHARS,
    MAX_WEB_SEARCH_URL_CHARS,
    WebSearchRequest,
    WebSearchResponse,
    WebSearchResult,
)

from agent_runtime.web_gateway import _NoRedirectHandler, _reject_non_public_resolution

JSON_CONTENT_TYPE = "application/json"
MAX_OUTPUT_CHARS = 20_000


class LocalWebSearchTransport:
    """Credential-free bounded SearXNG JSON adapter."""

    def execute(self, request: WebSearchRequest) -> WebSearchResponse:
        _reject_non_public_resolution(request.endpoint.hostname)
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
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
                content_type = response.headers.get("Content-Type", "").partition(";")[0]
                if content_type.strip().lower() != JSON_CONTENT_TYPE:
                    raise WebGatewayError(
                        "search response content type is not application/json",
                        reason="unsupported_content_type",
                    )
                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) > request.max_bytes:
                    raise WebGatewayError(
                        "search response exceeds the byte limit", reason="response_too_large"
                    )
                body = response.read(request.max_bytes + 1)
                if len(body) > request.max_bytes:
                    raise WebGatewayError(
                        "search response exceeds the byte limit", reason="response_too_large"
                    )
                return _normalize_response(body, request, len(body))
        except WebGatewayError:
            raise
        except urllib.error.HTTPError as exc:
            reason = "redirect_blocked" if 300 <= exc.code < 400 else "http_error"
            raise WebGatewayError(f"search gateway HTTP error: {exc.code}", reason=reason) from exc
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise WebGatewayError(f"search gateway request failed: {exc}") from exc


def _search_url(request: WebSearchRequest) -> str:
    separator = "&" if urllib.parse.urlsplit(request.endpoint.url).query else "?"
    query = urllib.parse.urlencode(
        {"q": request.query, "format": "json", "limit": request.limit}
    )
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
    normalized: list[WebSearchResult] = []
    seen_urls: set[str] = set()
    output_chars = 0
    raw_results = payload["results"]
    truncated = len(raw_results) > request.limit
    for item in raw_results:
        if len(normalized) >= request.limit:
            break
        result = _normalize_result(item)
        if result is None or result.url in seen_urls:
            truncated = True
            continue
        result_chars = len(result.title) + len(result.url) + len(result.snippet)
        if output_chars + result_chars > MAX_OUTPUT_CHARS:
            truncated = True
            break
        normalized.append(result)
        seen_urls.add(result.url)
        output_chars += result_chars
    return WebSearchResponse(
        results=tuple(normalized),
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
    title = (
        _bounded_text(value.get("title"), MAX_WEB_SEARCH_TITLE_CHARS)
        or target.hostname
    )
    snippet = _bounded_text(value.get("content"), MAX_WEB_SEARCH_SNIPPET_CHARS)
    return WebSearchResult(title=title, url=target.url, snippet=snippet)


def _bounded_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]
