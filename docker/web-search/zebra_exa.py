"""Explicit anonymous Exa supplement; Yahoo remains the default and fallback."""

import fcntl
import json
import logging
import math
import os
import tempfile
import threading
import time
import uuid
from email.utils import parsedate_to_datetime
from pathlib import Path

from curl_cffi.requests.exceptions import Timeout
from searx import network as _network
from searx.engines import engines
from searx.result_types import EngineResults
from searx.search.processors.online import default_request_params

about = {
    "website": "https://exa.ai/mcp",
    "use_official_api": True,
    "require_api_key": False,
    "results": "JSON",
}
categories = ["general", "web"]
paging = False
safesearch = True
ENDPOINT = "https://mcp.exa.ai/mcp?tools=web_search_advanced_exa"
STATE = Path(tempfile.gettempdir()) / "zebra-exa-control.json"
COOLDOWN = 900
MAX_COOLDOWN = 86400
EXA_BUDGET = 2.0
_session = None
OPTIONAL_CONFIG = {
    "name": "exa",
    "engine": "zebra_exa",
    "shortcut": "exa",
    "disabled": True,
    "inactive": False,
    "timeout": 6.0,
    "retries": 0,
}
if _proxy := os.environ.get("SEARXNG_EXA_PROXY") or os.environ.get("SEARXNG_YAHOO_PROXY"):
    proxies = _proxy


class ProviderError(ValueError):
    pass


class RateLimit(ProviderError):
    pass


def _state(change):
    # ponytail: tiny provider state, not query/auth caching; flock coordinates processes.
    # This is one shared local volume. Multiple hosts need a shared coordinator instead.
    fd = os.open(STATE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raw = handle.read(4097)
        state = json.loads(raw) if raw else {}
        if not isinstance(state, dict) or len(raw) > 4096:
            raise ValueError("invalid provider state")
        for key in ("until", "lease"):
            value = state.get(key, 0)
            if not isinstance(value, int | float) or not math.isfinite(value):
                raise ValueError("invalid provider deadline")
        result = change(state)
        handle.seek(0)
        handle.write(json.dumps(state, allow_nan=False))
        handle.truncate()
        handle.flush()
        return result


def _reserve():
    def change(state):
        now = time.time()
        if state.get("blocked") or max(state.get("until", 0), state.get("lease", 0)) > now:
            return False
        state["lease"] = now + EXA_BUDGET + 1
        state["owner"] = uuid.uuid4().hex
        return state["owner"]

    try:
        return _state(change)
    except (OSError, ValueError):
        return False  # Corrupt/unavailable control state never permits a fresh Exa probe.


def _finish(lease, reason=None, retry_after=None):
    now = time.time()
    delay = COOLDOWN if reason == "rate_limit" else 60
    if reason == "rate_limit" and retry_after:
        try:
            requested = float(retry_after)
        except ValueError:
            try:
                requested = parsedate_to_datetime(retry_after).timestamp() - now
            except (ValueError, TypeError, OverflowError):
                requested = 0
        if math.isfinite(requested):
            delay = max(delay, requested)

    def change(state):
        if state.get("owner") != lease:
            return
        state["lease"] = 0
        if reason:
            # Never probe earlier than a longer Retry-After. Over-cap recovery is manual.
            state["blocked"] = delay > MAX_COOLDOWN
            state["until"] = now + min(delay, MAX_COOLDOWN)

    _state(change)


def _message(resp, expected_id):
    if resp.status_code == 429:
        raise RateLimit("rate_limit")
    if resp.status_code != 200 or len(resp.content) > 262144:
        raise ProviderError("invalid_response")
    try:
        body = json.loads(resp.text)
    except ValueError:
        messages = []
        for block in resp.text.replace("\r\n", "\n").split("\n\n"):
            data = "\n".join(
                line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")
            )
            if data:
                messages.append(json.loads(data))
        matching = [m for m in messages if isinstance(m, dict) and m.get("id") == expected_id]
        if len(matching) != 1:
            raise ProviderError("invalid_rpc") from None
        body = matching[0]
    if not isinstance(body, dict) or body.get("id") != expected_id:
        raise ProviderError("invalid_rpc")
    if body.get("error"):
        _raise_provider(body["error"])
    result = body.get("result")
    if not isinstance(result, dict):
        raise ProviderError("invalid_result")
    if result.get("isError"):
        _raise_provider(result)
    return result


def _raise_provider(value):
    text = json.dumps(value).lower()
    if (isinstance(value, dict) and value.get("code") in (429, -32029)) or any(
        word in text for word in ("rate limit", "too many requests", "quota", "-32029")
    ):
        raise RateLimit("rate_limit")
    raise ProviderError("invalid_result")


def _results(resp):
    result = _message(resp, 2)
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise ProviderError("invalid_content")
    try:
        payload = json.loads(content[0]["text"])
    except (ValueError, KeyError, TypeError):
        _raise_provider(content)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ProviderError("invalid_sources")
    out = EngineResults()
    for item in payload["results"][:5]:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            raise ProviderError("invalid_source")
        out.add(
            out.types.MainResult(
                url=item["url"],
                title=str(item.get("title") or "")[:200],
                content=str(item.get("text") or "")[:1000],
            )
        )
    if not out:
        raise ProviderError("empty_sources")
    return out


def _restore(params):
    timeout, start = params["_exa_original"]
    _alive(params)
    _network.set_timeout_for_thread(timeout, start_time=start)


def _alive(params):
    timeout, start = params["_exa_original"]
    if (
        getattr(threading.current_thread(), "_timeout", False)
        or time.monotonic() >= start + timeout
    ):
        raise Timeout("request deadline reached")


def _yahoo(query, params):
    _restore(params)
    logging.getLogger("searx.engines.exa").info("Exa optional route=yahoo")
    _network.set_context_network_name("yahoo")
    params.update(default_request_params())  # Drop all MCP headers/body before Yahoo.
    params["_exa_fallback"] = True
    engines["yahoo"].request(query, params)


def _yahoo_results(resp):
    results = engines["yahoo"].response(resp)
    for item in results:
        if hasattr(item, "content"):
            item.content = "[Yahoo fallback] " + item.content
    return results


def request(query, params):
    global _session
    start = getattr(_network.THREADLOCAL, "start_time", None) or time.monotonic()
    timeout = getattr(_network.THREADLOCAL, "timeout", None) or 6.0
    params["_exa_original"] = (timeout, start)
    params["_exa_query"] = query
    _alive(params)
    params["_exa_lease"] = _reserve()
    if not params["_exa_lease"]:
        _yahoo(query, params)
        return
    logging.getLogger("searx.engines.exa").info("Exa optional route=exa")
    _network.set_timeout_for_thread(
        min(timeout, time.monotonic() - start + EXA_BUDGET), start_time=start
    )
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    try:
        if _session is None:
            resp = _network.post(
                ENDPOINT,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "zebra-search", "version": "1"},
                    },
                },
                headers=headers,
                allow_redirects=False,
                raise_for_httperror=False,
            )
            initialized = _message(resp, 1)
            protocol = initialized.get("protocolVersion")
            if protocol not in ("2025-03-26", "2025-06-18"):
                raise ProviderError("unsupported_protocol")
            headers["MCP-Protocol-Version"] = protocol
            if session_id := resp.headers.get("mcp-session-id"):
                headers["Mcp-Session-Id"] = session_id
            _alive(params)
            resp = _network.post(
                ENDPOINT,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=headers,
                allow_redirects=False,
                raise_for_httperror=False,
            )
            if resp.status_code == 429:
                raise RateLimit("rate_limit")
            if resp.status_code not in (200, 202, 204):
                raise ProviderError("initialization_failed")
            _session = headers.copy()  # Anonymous provider session only, never Cloud authority.
        _alive(params)
        params.update(
            {
                "url": ENDPOINT,
                "method": "POST",
                "headers": _session.copy(),
                "raise_for_httperror": False,
                "json": {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "web_search_advanced_exa",
                        "arguments": {
                            "query": query,
                            "type": "fast",
                            "numResults": 5,
                            "enableSummary": False,
                            "enableHighlights": False,
                            "textMaxCharacters": 1000,
                            "livecrawlTimeout": 1000,
                            "moderation": bool(params["safesearch"]),
                        },
                    },
                },
            }
        )
    except (ProviderError, ValueError, TypeError, KeyError) as error:
        _session = None
        _finish(
            params["_exa_lease"],
            "rate_limit" if isinstance(error, RateLimit) else "provider_error",
            resp.headers.get("retry-after"),
        )
        _yahoo(query, params)


def response(resp):
    global _session
    params = resp.search_params
    if params.get("_exa_fallback"):
        return _yahoo_results(resp)
    try:
        out = _results(resp)
    except (ProviderError, ValueError, TypeError, KeyError) as error:
        _session = None
        _finish(
            params["_exa_lease"],
            "rate_limit" if isinstance(error, RateLimit) else "provider_error",
            resp.headers.get("retry-after"),
        )
        _yahoo(params["_exa_query"], params)
        fallback = _network.get(
            params["url"],
            headers=params["headers"],
            cookies=params["cookies"],
            allow_redirects=False,
            raise_for_httperror=False,
        )
        fallback.search_params = params
        return _yahoo_results(fallback)
    _finish(params["_exa_lease"])
    _restore(params)
    return out
