"""Bounded, non-secret diagnostics for an incomplete upstream search response."""

from __future__ import annotations

import re
from collections.abc import Mapping

from agent_tools.mcp_proxy import JsonValue
from agent_tools.web_gateway import WebGatewayError


def require_complete_search(payload: Mapping[str, object]) -> None:
    raw = payload.get("unresponsive_engines")
    if not raw and not payload.get("error"):
        return
    failures: list[JsonValue] = []
    retryable = bool(raw) and not payload.get("error")
    for item in (raw if isinstance(raw, list) else [None])[:8]:
        engine, detail = item[:2] if isinstance(item, list) and len(item) >= 2 else ("unknown", "")
        engine = re.sub(r"[^a-zA-Z0-9_. -]", "", str(engine))[:40] or "unknown"
        text = str(detail).lower()
        code = (
            "suspended"
            if text.startswith("suspended:")
            else "captcha"
            if "captcha" in text
            else "rate_limited"
            if "too many" in text or "429" in text
            else "access_denied"
            if "access denied" in text or "403" in text
            else "timeout"
            if "timeout" in text
            else "unavailable"
            if "connection" in text
            else "upstream_error"
        )
        retryable = bool(retryable and code in {"timeout", "unavailable"})
        failures.append({"engine": engine, "code": code})
    results = payload.get("results")
    metadata: dict[str, JsonValue] = {
        "engine_failures": failures,
        "candidate_count": len(results) if isinstance(results, list) else 0,
        "source_complete": False,
        "execution_state": "not_executed"
        if isinstance(raw, list) and 0 < len(raw) <= 8
        and all(isinstance(item, dict) and item["code"] == "suspended" for item in failures)
        and isinstance(results, list) and not results and not payload.get("error")
        else "executed",
        "category": "upstream_search",
        "retryable": bool(retryable),
    }
    if retryable:
        metadata["retry_after_seconds"] = 5
    # Never echo raw upstream text, URLs, headers, query strings or credentials.
    labels = [f"{item['engine']}={item['code']}" for item in failures if isinstance(item, dict)]
    raise WebGatewayError(
        "search source query is incomplete: " + ", ".join(labels),
        reason="search_incomplete",
        metadata=metadata,
    )
