from datetime import UTC, datetime

from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from zebra_agent_api.routes import RouteRequest
from zebra_agent_api.usage_api import handle_usage_route, summarize_usage


def _context() -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id="grant",
        host_app_id="trench",
        namespace_id="workspace",
        workspace_ref="workspace",
        resource_refs=(HostResourceRef(type="principal", id="user-1"),),
        scopes=("event.read",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=100,
            max_model_tokens=1000,
            max_artifact_bytes=1000,
        ),
        origin="https://trench.example.com",
        policy_version="v1",
    )


class _Reader:
    deployment_namespace = "test"

    def __init__(self) -> None:
        self.context = None

    def read(self, context: HostContextEnvelope, *, start: datetime, end: datetime) -> list[dict]:
        self.context = context
        return []


def test_usage_requires_principal_scoped_event_read_grant() -> None:
    reader = _Reader()
    request = RouteRequest(method="GET", path="/usage")
    assert handle_usage_route(reader, request).status_code == 401  # type: ignore[union-attr]
    request = RouteRequest(
        method="GET", path="/usage", host_context=_context(), query={"days": "7"}
    )
    response = handle_usage_route(reader, request)
    assert response is not None and response.status_code == 200
    assert reader.context == _context()
    assert response.body["period"]["days"] == 7


def test_usage_counts_only_provider_reported_tokens_and_flags_missing_metering() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    base = {"created_at": start, "task_id": "t1", "title": "Test"}
    result = summarize_usage(
        [
            {
                **base,
                "event_type": "model_response_received",
                "input_tokens": "12",
                "output_tokens": "4",
                "reasoning_tokens": "2",
                "resolved_model": "model-a",
            },
            {**base, "event_type": "model_response_received", "resolved_model": "model-a"},
            {**base, "event_type": "tool_execution_completed", "tool_name": "search"},
            {**base, "event_type": "user_message_received"},
        ],
        days=7,
        start=start,
    )
    totals = result["totals"]
    assert totals["total_tokens"] == 16
    assert totals["reasoning_tokens"] == 2
    assert totals["unmetered_calls"] == 1
    assert totals["tool_calls"] == 1
    assert result["tasks"][0]["total_tokens"] == 16
