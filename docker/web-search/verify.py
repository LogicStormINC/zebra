"""Operator acceptance: execute the actual search adapter, without model/SQL calls."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query", action="append", help="Query to qualify; repeat for multiple queries"
    )
    args = parser.parse_args()
    from agent_core.domain.identifiers import new_tool_call_id
    from agent_core.domain.tools import ToolCall, ToolCallStatus
    from agent_core.domain.web import parse_web_target
    from agent_core.harness.evidence_ledger import evidence_ledger, record_tool_evidence
    from agent_core.harness.quality_gates import _unsupported_urls
    from agent_runtime.web_search import LocalWebSearchTransport
    from agent_tools.web_search import WebSearchTool
    from zebra_agent_config import load_settings

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
    for query in args.query or ["OpenAI news", "OpenAI latest official announcement news release"]:
        result = tool.handle(
            ToolCall(
                tool_call_id=new_tool_call_id(),
                name="web.search",
                arguments={"query": query, "limit": 5},
                created_at=datetime.now(UTC),
            )
        )
        ledger = evidence_ledger([], record_tool_evidence({}, result))
        ready = (
            result.status is ToolCallStatus.EXECUTED
            and bool(ledger.evidence_refs)
            and not _unsupported_urls(result.output, ledger.evidence_refs)
        )
        passed = bool(passed and ready)
        # Counts/status only: no tenant data, result body, auth headers or env dumps.
        print(
            json.dumps(
                {
                    "ready": bool(ready),
                    "status": result.status.value,
                    "source_count": len(ledger.evidence_refs),
                    "reason": result.metadata.get("reason"),
                    "engine_failures": result.metadata.get("engine_failures"),
                },
                ensure_ascii=False,
            )
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
