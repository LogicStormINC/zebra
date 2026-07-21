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

from agent_core.domain.web import WebTargetError, parse_web_target
from agent_tools.search_pipeline import SearchHit, SearchQuery

from agent_runtime.web_gateway import _NoRedirectHandler, _proxy_configuration

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

    def search(self, query: SearchQuery, *, limit: int) -> tuple[SearchHit, ...]:
        fetch = self.fetch_json or urllib_fetch_json(self.use_system_proxy)
        url = _searxng_url(self.endpoint, query=query, limit=limit)
        payload = fetch(url)
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            return ()
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for item in payload["results"]:
            if len(hits) >= limit:
                break
            hit = _hit_from_searxng(item)
            if hit is None or hit.url in seen:
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


def urllib_fetch_json(use_system_proxy: bool = False) -> FetchJson:
    """Build a fetch_json callable over urllib with no-redirect + proxy control."""

    def _fetch(url: str) -> object:
        hostname = urllib.parse.urlsplit(url).hostname or ""
        proxies = _proxy_configuration(hostname, use_system_proxy=use_system_proxy)
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies),
            _NoRedirectHandler(),
        )
        request = urllib.request.Request(
            url,
            headers={"Accept": JSON_CONTENT_TYPE, "User-Agent": "Zebra-Agent-Web-Search/2.0"},
            method="GET",
        )
        try:
            with opener.open(request) as response:
                content_type = response.headers.get("Content-Type", "").partition(";")[0]
                if content_type.strip().lower() != JSON_CONTENT_TYPE:
                    return {}
                body = response.read(MAX_SEARCH_RESPONSE_BYTES)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                return {}
            raise
        except (OSError, ValueError):
            return {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    return _fetch
