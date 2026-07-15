from datetime import UTC, datetime

from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall
from agent_security.mcp_proxy_policy import ToolEgressRoute, classify_tool_egress
from agent_security.network_profile import parse_network_profile


def test_classify_tool_egress_marks_builtin_tool_as_local() -> None:
    metadata = classify_tool_egress(
        _tool_call("files.read", {"path": "README.md"}),
        network_profile=parse_network_profile("none"),
    )

    assert metadata.route is ToolEgressRoute.LOCAL
    assert metadata.target is None
    assert metadata.to_mapping()["route"] == "local"


def test_classify_tool_egress_blocks_mcp_tool_without_proxy_profile() -> None:
    metadata = classify_tool_egress(
        _tool_call("mcp.github.create_pull_request", {"title": "Add feature"}),
        network_profile=parse_network_profile("none"),
    )

    assert metadata.route is ToolEgressRoute.BLOCKED
    assert metadata.target == "github.create_pull_request"
    assert metadata.network_profile == "none"


def test_classify_tool_egress_marks_mcp_tool_as_proxy_routable() -> None:
    metadata = classify_tool_egress(
        _tool_call("mcp.github.create_pull_request", {"title": "Add feature"}),
        network_profile=parse_network_profile("mcp-proxy-only"),
    )

    assert metadata.route is ToolEgressRoute.MCP_PROXY
    assert metadata.target == "github.create_pull_request"
    assert metadata.to_mapping()["route"] == "mcp_proxy"


def test_classify_web_fetch_requires_exact_durable_allowlist_match() -> None:
    allowed = classify_tool_egress(
        _tool_call("web.fetch", {"url": "https://docs.example.com/guide"}),
        network_profile=parse_network_profile(
            "domain-allowlist", domain_allowlist=("docs.example.com",)
        ),
    )
    blocked = classify_tool_egress(
        _tool_call("web.fetch", {"url": "https://sub.docs.example.com/guide"}),
        network_profile=parse_network_profile(
            "domain-allowlist", domain_allowlist=("docs.example.com",)
        ),
    )

    assert allowed.route is ToolEgressRoute.WEB_GATEWAY
    assert allowed.target == "docs.example.com"
    assert blocked.route is ToolEgressRoute.BLOCKED


def _tool_call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
    )
