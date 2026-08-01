from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import zebra_agent_api.app as api_app_module
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.policies import PolicyDecisionType
from agent_core.domain.tools import ToolCall
from agent_security import LocalPolicyEngine, PolicyProfile, parse_network_profile
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_create_session_preapproved_readonly_tools_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    monkeypatch.setattr(
        api_app_module,
        "validate_mcp_capability_selection",
        lambda _servers, selected: tuple(selected),
    )
    settings = replace(_settings(database_path), profile="local")
    payload = {
        "prompt": "Search public sources",
        "policy_profile": "read_only",
        "network_profile": "mcp-proxy-only",
        "mcp_allowlist": ["mcp.catalog.search_public"],
        "preapproved_readonly_tools": ["mcp.catalog.search_public"],
    }

    client = TestClient(create_http_app(database_path, settings=settings))
    response = client.post("/tasks", json=payload)

    assert response.status_code == 201
    assert response.json()["network_profile"] == "mcp-proxy-only"
    assert response.json()["preapproved_readonly_tools"] == [
        "mcp.catalog.search_public"
    ]
    detail = client.get(f"/tasks/{response.json()['task_id']}")
    assert detail.json()["workspace"]["preapproved_readonly_tools"] == [
        "mcp.catalog.search_public"
    ]

    unknown = client.post("/tasks", json={**payload, "not_a_create_session_field": True})
    assert unknown.status_code == 400
    assert unknown.json()["reason"] == "unknown create-session fields: not_a_create_session_field"

    legacy_payload = {
        key: value for key, value in payload.items() if key != "preapproved_readonly_tools"
    }
    legacy = client.post("/tasks", json=legacy_payload)
    assert legacy.status_code == 201
    assert legacy.json()["preapproved_readonly_tools"] == []

    engine = LocalPolicyEngine(
        profile=PolicyProfile.READ_ONLY,
        network_profile=parse_network_profile("mcp-proxy-only"),
        mcp_allowlist=("mcp.catalog.search_public",),
        preapproved_readonly_tools=("mcp.catalog.search_public",),
    )
    allowed = engine.evaluate_tool_call(_tool_call("mcp.catalog.search_public"))
    ungranted = engine.evaluate_tool_call(_tool_call("mcp.catalog.publish_report"))
    assert allowed.decision is PolicyDecisionType.ALLOW
    assert ungranted.decision is PolicyDecisionType.REQUIRE_APPROVAL


def _settings(database_path: Path) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database_path),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )


def _tool_call(name: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
