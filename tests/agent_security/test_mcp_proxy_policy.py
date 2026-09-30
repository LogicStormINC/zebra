from datetime import UTC, datetime

from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.policies import PolicyDecisionType
from agent_core.domain.tools import ToolCall
from agent_security import LocalPolicyEngine, PolicyProfile
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


def test_classify_web_fetch_allows_public_target_for_trusted_local_profile() -> None:
    metadata = classify_tool_egress(
        _tool_call("web.fetch", {"url": "https://docs.example.com/guide"}),
        network_profile=parse_network_profile("full-trusted-local"),
    )

    assert metadata.route is ToolEgressRoute.WEB_GATEWAY
    assert metadata.target == "docs.example.com"


def test_native_web_crawl_and_extract_use_the_fetch_network_ceiling() -> None:
    profile = parse_network_profile(
        "domain-allowlist", domain_allowlist=("docs.example.com",)
    )
    for name in ("web.crawl", "web.extract"):
        allowed = classify_tool_egress(
            _tool_call(name, {"url": "https://docs.example.com/guide"}),
            network_profile=profile,
            web_pipeline_v2=True,
        )
        blocked = classify_tool_egress(
            _tool_call(name, {"url": "https://other.example.com/guide"}),
            network_profile=profile,
            web_pipeline_v2=True,
        )
        assert allowed.route is ToolEgressRoute.WEB_GATEWAY
        assert blocked.route is ToolEgressRoute.BLOCKED
        assert classify_tool_egress(
            _tool_call(name, {"url": "https://docs.example.com/guide"}),
            network_profile=profile,
        ).route is ToolEgressRoute.LOCAL


def test_native_web_tools_follow_network_authority_without_blocking_cached_reads() -> None:
    allowed = LocalPolicyEngine(
        profile=PolicyProfile.READ_ONLY,
        network_profile=parse_network_profile(
            "domain-allowlist", domain_allowlist=("docs.example.com",)
        ),
        web_pipeline_v2=True,
    )
    blocked = LocalPolicyEngine(
        profile=PolicyProfile.READ_ONLY,
        network_profile=parse_network_profile("mcp-proxy-only"),
        web_pipeline_v2=True,
    )
    for name in ("web.crawl", "web.extract"):
        args = {"url": "https://docs.example.com/guide"}
        assert (
            allowed.evaluate_tool_call(_tool_call(name, args)).decision
            is PolicyDecisionType.ALLOW
        )
        denied = blocked.evaluate_tool_call(_tool_call(name, args))
        assert denied.decision is PolicyDecisionType.DENY
        assert denied.route == "blocked"
    for name in ("web.read", "web.find"):
        assert blocked.evaluate_tool_call(_tool_call(name, {})).decision is PolicyDecisionType.ALLOW
        assert LocalPolicyEngine(web_pipeline_v2=False).evaluate_tool_call(
            _tool_call(name, {})
        ).decision is PolicyDecisionType.DENY


def test_native_search_auto_fetch_cannot_bypass_the_endpoint_allowlist() -> None:
    args = {"query": "zebra agent", "auto_fetch": 1}
    restricted = LocalPolicyEngine(
        network_profile=parse_network_profile(
            "domain-allowlist", domain_allowlist=("search.example.com",)
        ),
        web_search_endpoint="https://search.example.com/search",
        web_pipeline_v2=True,
    )
    denied = restricted.evaluate_tool_call(_tool_call("web.search", args))
    assert denied.decision is PolicyDecisionType.DENY
    assert denied.route == "blocked"
    assert "auto_fetch" in classify_tool_egress(
        _tool_call("web.search", args),
        network_profile=restricted.network_profile,
        web_search_endpoint=restricted.web_search_endpoint,
        web_pipeline_v2=True,
    ).reason

    trusted = LocalPolicyEngine(
        network_profile=parse_network_profile("full-trusted-local"),
        web_search_endpoint="https://search.example.com/search",
        web_pipeline_v2=True,
    )
    assert trusted.evaluate_tool_call(_tool_call("web.search", args)).decision is (
        PolicyDecisionType.ALLOW
    )


def _tool_call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
    )
