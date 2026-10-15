"""Qualify collected search sources separately from transport, without model/SQL calls."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from urllib.parse import urlsplit

# ponytail: fixed public canaries; use --query/--expect-source for other workloads.
_DEFAULT_CHECKS = (
    (
        "PostgreSQL 18 released official announcement site:postgresql.org",
        "https://www.postgresql.org/about/news/postgresql-18-released-3142/",
    ),
    (
        "Redis 8 general availability release announcement site:redis.io",
        "https://redis.io/blog/redis-8-ga/",
    ),
)


def _matches_source(source: str, expected: str) -> bool:
    actual, target = urlsplit(source), urlsplit(expected)
    path = target.path.rstrip("/")
    return (
        actual.scheme == target.scheme
        and actual.netloc.lower() == target.netloc.lower()
        and (actual.path.rstrip("/") == path or actual.path.startswith(path + "/"))
        and (not target.query or actual.query == target.query)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query", action="append", help="Query to qualify; repeat for multiple queries"
    )
    parser.add_argument(
        "--expect-source", action="append", help="Expected HTTPS origin/path, one per --query"
    )
    parser.add_argument(
        "--transport-only", action="store_true", help="Check transport only; never sets ready=true"
    )
    args = parser.parse_args()
    if args.transport_only and args.expect_source:
        parser.error("--transport-only cannot be combined with --expect-source")
    if not args.transport_only and bool(args.query) != bool(args.expect_source):
        parser.error("each --query requires one --expect-source; or use --transport-only")
    if args.expect_source and len(args.query) != len(args.expect_source):
        parser.error("each --query requires exactly one --expect-source")
    checks = (
        [(q, None) for q in args.query or [q for q, _ in _DEFAULT_CHECKS]]
        if args.transport_only
        else list(zip(args.query, args.expect_source, strict=True))
        if args.query
        else _DEFAULT_CHECKS
    )
    from agent_core.domain.identifiers import new_tool_call_id
    from agent_core.domain.tools import ToolCall, ToolCallStatus
    from agent_core.domain.web import parse_web_target
    from agent_core.harness.evidence_ledger import evidence_ledger, record_tool_evidence
    from agent_core.harness.quality_gates import _unsupported_urls
    from agent_runtime.web_search import LocalWebSearchTransport
    from agent_tools.web_search import WebSearchTool
    from zebra_agent_config import load_settings

    for _, expected in checks:
        if expected is not None:
            try:
                parse_web_target(expected)
            except ValueError:
                parser.error("--expect-source must be a valid public HTTPS URL")
    settings = load_settings()
    if not settings.web_search_endpoint:
        print("FAIL: no configured search endpoint")
        return 1
    endpoint = settings.web_search_endpoint
    options = {
        "trusted_search_endpoint": endpoint if settings.web_search_private_backend else None,
        "network_cancellation_check": lambda: None,
    }
    if settings.web_pipeline_v2:
        from agent_runtime.search_providers import SearXNGSearchProvider
        from agent_tools.search_pipeline import (
            SearchPipeline,
            SearchPipelineTool,
            SearchProviderRegistry,
        )

        registry = SearchProviderRegistry()
        registry.register(SearXNGSearchProvider(endpoint=endpoint, **options), default=True)
        tool = SearchPipelineTool(SearchPipeline(registry))
    else:
        tool = WebSearchTool(parse_web_target(endpoint), LocalWebSearchTransport(**options))
    passed = True
    for query, expected in checks:
        result = tool.handle(
            ToolCall(
                tool_call_id=new_tool_call_id(),
                name="web.search",
                arguments={"query": query, "limit": 5},
                created_at=datetime.now(UTC),
            )
        )
        ledger = evidence_ledger([], record_tool_evidence({}, result))
        transport_ready = (
            result.status is ToolCallStatus.EXECUTED
            and bool(ledger.evidence_refs)
            and not _unsupported_urls(result.output, ledger.evidence_refs)
        )
        matched = expected is not None and any(
            _matches_source(ref, expected) for ref in ledger.evidence_refs
        )
        ready = bool(transport_ready and matched)
        passed = bool(passed and (transport_ready if args.transport_only else ready))
        # Counts/status only: no tenant data, result body, auth headers or env dumps.
        print(
            json.dumps(
                {
                    "ready": bool(ready),
                    "transport_ready": bool(transport_ready),
                    "quality_checked": expected is not None,
                    "expected_source_found": bool(matched),
                    "status": result.status.value,
                    "source_count": len(ledger.evidence_refs),
                    "reason": result.metadata.get("reason")
                    or (
                        "expected_source_missing"
                        if transport_ready and expected and not matched
                        else "transport_only"
                        if args.transport_only
                        else None
                    ),
                    "engine_failures": result.metadata.get("engine_failures"),
                },
                ensure_ascii=False,
            )
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
