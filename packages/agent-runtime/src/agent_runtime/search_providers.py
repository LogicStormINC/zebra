"""Search provider implementations for the rebuilt web.search pipeline.

``SearXNGSearchProvider`` is the local-first default (credential-free, no vendor
egress). The HTTP layer is injected so tests run fully offline; production uses
``urllib_fetch_json`` built on the same no-redirect / proxy discipline as the
legacy transport.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException

from agent_core.domain.web import WebTargetError, parse_web_target
from agent_tools.search_pipeline import SearchHit, SearchQuery
from agent_tools.web_gateway import WebGatewayError
from agent_tools.web_search import DEFAULT_WEB_SEARCH_TIMEOUT_SECONDS

from agent_runtime.search_egress import search_network_options
from agent_runtime.web_gateway import (
    _native_network_call,
    _NoRedirectHandler,
    _read_bounded_body,
)

FetchJson = Callable[[str], object]
JSON_CONTENT_TYPE = "application/json"
MAX_SEARCH_RESPONSE_BYTES = 512 * 1024


@dataclass
class SearXNGSearchProvider:
    name: str = "searxng"
    endpoint: str = ""
    fetch_json: FetchJson | None = None
    available: bool = True
    use_system_proxy: bool = False
    network_cancellation_check: Callable[[], None] | None = None
    trusted_search_endpoint: str | None = None

    def search(self, query: SearchQuery, *, limit: int) -> tuple[SearchHit, ...]:
        fetch = self.fetch_json or urllib_fetch_json(
            self.use_system_proxy,
            network_cancellation_check=self.network_cancellation_check,
            trusted_search_endpoint=self.trusted_search_endpoint,
        )
        url = _searxng_url(self.endpoint, query=query, limit=limit)
        payload = fetch(url)
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise WebGatewayError("invalid search response shape", reason="invalid_search_response")
        if payload.get("unresponsive_engines") or payload.get("error"):
            # ponytail: the tuple provider contract cannot attest partial engine coverage.
            raise WebGatewayError("search source query is incomplete", reason="search_incomplete")
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for item in payload["results"]:
            if len(hits) >= limit:
                break
            hit = _hit_from_searxng(item)
            if hit is None:
                raise WebGatewayError("invalid search candidate", reason="invalid_search_response")
            if hit.url in seen:
                continue
            seen.add(hit.url)
            hits.append(hit)
        return tuple(hits)


def _searxng_url(endpoint: str, *, query: SearchQuery, limit: int) -> str:
    base = endpoint.split("#", 1)[0]
    separator = "&" if urllib.parse.urlsplit(base).query else "?"
    params: dict[str, str] = {
        "q": query.query,
        "format": "json",
        "limit": str(limit),
    }
    if query.time_range:
        params["time_range"] = query.time_range
    if query.include_domains:
        # SearXNG supports per-engine site filters indirectly; we still apply
        # Zebra-side filtering, but hint the engine when domains are given.
        params["sites"] = ",".join(query.include_domains)
    return f"{base}{separator}{urllib.parse.urlencode(params)}"


def _hit_from_searxng(item: object) -> SearchHit | None:
    if not isinstance(item, dict):
        return None
    raw_url = item.get("url")
    if not isinstance(raw_url, str):
        return None
    try:
        target = parse_web_target(urllib.parse.urldefrag(raw_url).url)
    except WebTargetError:
        return None
    title = _bounded(item.get("title"), 200) or target.hostname
    snippet = _bounded(item.get("content"), 1_000)
    return SearchHit(
        title=title,
        url=target.url,
        snippet=snippet,
        domain=target.hostname,
        freshness=None,
    )


def _bounded(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def urllib_fetch_json(
    use_system_proxy: bool = False,
    *,
    network_cancellation_check: Callable[[], None] | None = None,
    trusted_search_endpoint: str | None = None,
) -> FetchJson:
    """Build a fetch_json callable over urllib with no-redirect + proxy control."""

    def _fetch(url: str) -> object:
        if network_cancellation_check is not None:
            return _native_network_call(
                "search_json",
                url,
                network_cancellation_check,
                timeout=DEFAULT_WEB_SEARCH_TIMEOUT_SECONDS,
                use_system_proxy=use_system_proxy,
                max_output_bytes=MAX_SEARCH_RESPONSE_BYTES * 6 + 65536,
                trusted_search_endpoint=trusted_search_endpoint,
            )
        proxies, https_handler = search_network_options(
            url, trusted_search_endpoint, use_system_proxy=use_system_proxy
        )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies),
            _NoRedirectHandler(),
            *((https_handler,) if https_handler is not None else ()),
        )
        request = urllib.request.Request(
            url,
            headers={"Accept": JSON_CONTENT_TYPE, "User-Agent": "Zebra-Agent-Web-Search/2.0"},
            method="GET",
        )
        try:
            with opener.open(request, timeout=DEFAULT_WEB_SEARCH_TIMEOUT_SECONDS) as response:
                if response.status == 206:
                    raise WebGatewayError(
                        "search source query is incomplete", reason="search_incomplete"
                    )
                content_type = response.headers.get("Content-Type", "").partition(";")[0]
                if content_type.strip().lower() != JSON_CONTENT_TYPE:
                    raise WebGatewayError(
                        "search response is not JSON", reason="unsupported_content_type"
                    )
                body = _read_bounded_body(response, MAX_SEARCH_RESPONSE_BYTES)
        except urllib.error.HTTPError as exc:
            reason = (
                "redirect_blocked"
                if 300 <= exc.code < 400
                else "access_denied"
                if exc.code in (401, 403)
                else "http_error"
            )
            exc.close()
            raise WebGatewayError(f"search HTTP error: {exc.code}", reason=reason) from exc
        except HTTPException as exc:
            raise WebGatewayError(
                "search response body is incomplete", reason="response_incomplete"
            ) from exc
        except (OSError, ValueError) as exc:
            raise WebGatewayError("search request unavailable") from exc
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise WebGatewayError(
                "search response is invalid JSON", reason="invalid_search_response"
            ) from exc
        return payload

    return _fetch
