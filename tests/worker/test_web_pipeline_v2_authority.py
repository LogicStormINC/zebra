"""Durable-authority alignment for the native v2 web pipeline (WEB-PIPE).

Proves the opt-in v2 ``web.fetch`` / ``web.search`` respect the SAME durable
network authority and execute-once semantics as v1: egress is classified by tool
name in ``classify_tool_egress`` (so v2, keeping the names, is covered), and
execution idempotency is the general tool-run guarantee. Shared session/execution
helpers are imported from ``test_approved_continuation``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tools import ToolCall
from agent_storage import SQLiteEventStore

# Same-dir helpers (pytest prepend mode puts tests/worker on sys.path).
from test_approved_continuation import (
    _execution_service,
    _gateway,
    _seed_session,
    _settings,
)
from web_v2_providers import RecordingFetchProvider, RecordingSearchProvider


def test_web_fetch_v2_uses_durable_network_authority_and_executes_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[name-defined]
) -> None:
    database_path = tmp_path / "web-v2-continuation.sqlite"
    created_at = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="web.fetch",
        arguments={"url": "https://docs.example.com/guide"},
        created_at=created_at,
        provider_call_id="call_web_v2_authorized",
    )
    gateway = _gateway(
        "Reading authorized Web content.",
        tool_call=tool_call,
        follow_up="authorized-web-output-v2",
        canonical="authorized-web-output-v2",
    )
    provider = RecordingFetchProvider()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )
    monkeypatch.setattr(
        "agent_runtime.web_tools.LocalHttpFetchProvider",
        lambda **kwargs: provider,
    )
    # Neutralize runtime DNS so the offline test does not depend on resolution.
    monkeypatch.setattr(
        "agent_runtime.crawl_gateway.resolve_and_validate",
        lambda *args, **kwargs: ("93.184.216.34",),
    )
    session_id = _seed_session(database_path, tmp_path, network_profile="none")
    service = _execution_service(
        database_path,
        settings=_settings(database_path, profile="local", web_pipeline_v2=True),
    )

    completed = service.execute_session(
        session_id, worker_id="worker-web-v2", executed_at=created_at
    )

    assert completed.session.status is SessionStatus.COMPLETED
    assert completed.attempt_result.metadata["assistant_message"] == "authorized-web-output-v2"
    assert len(provider.requests) == 1
    assert provider.requests[0].url == "https://docs.example.com/guide"
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert (
        sum(
            event.event_type is EventType.TOOL_EXECUTION_STARTED
            and event.payload.get("tool_name") == "web.fetch"
            for event in events
        )
        == 1
    )


def test_web_search_v2_uses_durable_network_authority_and_executes_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[name-defined]
) -> None:
    database_path = tmp_path / "search-v2-continuation.sqlite"
    created_at = datetime(2026, 7, 15, 8, 30, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="web.search",
        arguments={"query": "zebra agent", "limit": 2},
        created_at=created_at,
        provider_call_id="call_search_v2_authorized",
    )
    gateway = _gateway(
        "Searching authorized sources.",
        tool_call=tool_call,
        follow_up="authorized-search-output-v2",
        canonical="authorized-search-output-v2",
    )
    provider = RecordingSearchProvider(endpoint="https://search.example.com/search")
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )
    monkeypatch.setattr(
        "agent_runtime.web_tools.SearXNGSearchProvider",
        lambda **kwargs: provider,
    )
    session_id = _seed_session(
        database_path,
        tmp_path,
        network_profile="domain-allowlist",
        network_allowlist=("search.example.com",),
    )
    settings = _settings(
        database_path,
        web_search_endpoint="https://search.example.com/search",
        web_pipeline_v2=True,
    )
    service = _execution_service(database_path, settings=settings)

    completed = service.execute_session(
        session_id, worker_id="worker-search-v2", executed_at=created_at
    )

    assert completed.session.status is SessionStatus.COMPLETED
    # the rebuilt pipeline may expand the query (multi-query/RRF), but the TOOL
    # must execute exactly once under the durable authority.
    assert provider.queries
    assert any(query == "zebra agent" for query in provider.queries)
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert (
        sum(
            event.event_type is EventType.TOOL_EXECUTION_STARTED
            and event.payload.get("tool_name") == "web.search"
            for event in events
        )
        == 1
    )
