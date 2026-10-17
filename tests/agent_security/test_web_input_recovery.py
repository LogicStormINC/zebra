from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall
from agent_core.harness.policy_step import recoverable_egress_denial
from agent_security import LocalPolicyEngine, PolicyProfile
from agent_security.network_profile import parse_network_profile


def call(arguments):
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="web.search",
        arguments=arguments,
        created_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("v2", [False, True])
def test_invalid_search_arguments_are_correctable_not_network_denials(v2):
    engine = LocalPolicyEngine(
        profile=PolicyProfile.FULL_ACCESS,
        network_profile=parse_network_profile("full-gateway"),
        web_search_endpoint="https://search.example.com/search",
        web_pipeline_v2=v2,
    )
    invalid = call({"query": "BTC", "limit": "5"})
    decision = engine.evaluate_tool_call(invalid)
    assert decision.route == "invalid_arguments"
    assert "limit must be an integer" in decision.reason
    result = recoverable_egress_denial(invalid, decision, read_only_tools=frozenset({"web.search"}))
    assert result is not None
    assert result.metadata["reason"] == "invalid_tool_arguments"
    assert result.metadata["executed"] is False
    assert "Correct" in result.output
    assert engine.evaluate_tool_call(call({"query": "BTC", "limit": 5})).decision.value == "allow"


def test_real_network_denial_stays_blocked():
    engine = LocalPolicyEngine(
        profile=PolicyProfile.FULL_ACCESS,
        network_profile=parse_network_profile("none"),
        web_search_endpoint="https://search.example.com/search",
    )
    request = call({"query": "BTC", "limit": 5})
    decision = engine.evaluate_tool_call(request)
    assert decision.route == "blocked"
    result = recoverable_egress_denial(request, decision, read_only_tools=frozenset({"web.search"}))
    assert result.metadata["reason"] == "policy_blocked_egress"
