"""Narrow model-wire normalization precedes strict policy and preserves replay."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.domain.web_search import WebSearchInputError, parse_web_search_input
from agent_integrations.openai_payloads import serialize_message
from agent_runtime.harness import LocalToolGateway
from agent_security import LocalPolicyEngine, parse_network_profile


def call(limit: object = "5", *, name: str = "web.search") -> ToolCall:
    return ToolCall(tool_call_id=new_tool_call_id(), name=name,
                    arguments={"query": "official release", "limit": limit},
                    provider_call_id="wire-1", created_at=datetime.now(UTC))


@pytest.mark.parametrize("value", ["1", "2", "3", "4", "5"])
@pytest.mark.parametrize("v2", [False, True])
def test_model_limit_is_typed_before_policy_and_raw_continuation_is_unchanged(
    tmp_path: Path, value: str, v2: bool,
):
    gateway = LocalToolGateway(tmp_path, web_pipeline_v2=v2,
                               web_search_endpoint="https://search.example.com/")
    original = call(value)
    try:
        resolved, = gateway.resolve_model_tool_calls((original,))
        assert type(resolved.arguments["limit"]) is int
        assert resolved.arguments == {**original.arguments, "limit": int(value)}
        assert original.arguments["limit"] == value
        assert (resolved.tool_call_id, resolved.provider_call_id, resolved.created_at) == (
            original.tool_call_id, original.provider_call_id, original.created_at)
        assert resolved.provider_arguments == original.arguments
        assert resolved.provider_tool_name == original.name
        assert parse_web_search_input(resolved.arguments).limit == int(value)
        policy = LocalPolicyEngine(
            network_profile=parse_network_profile("full-gateway"),
            web_search_endpoint="https://search.example.com/",
        )
        assert policy.evaluate_tool_call(resolved).decision.value == "allow"
        message = SessionMessage(message_id=new_message_id(),
                                 role=MessageRole.ASSISTANT, content="Tool calls proposed.",
                                 tool_calls=(resolved,), created_at=original.created_at)
        wire = serialize_message(message)["tool_calls"][0]["function"]
        assert wire["name"] == "web__search"
        assert json.loads(wire["arguments"]) == original.arguments
        assert gateway.resolve_model_tool_calls((resolved,))[0] is resolved
    finally:
        gateway.close()


@pytest.mark.parametrize("value", ["0", "6", "05", "+5", "-1", "5.0", "5e0", " 5", "5 ",
                                  "５", "٥", "true", "", None, True, 5.0, [], {}, 0, 6])
def test_ambiguous_or_invalid_limits_are_still_rejected(tmp_path: Path, value: object):
    gateway = LocalToolGateway(tmp_path, web_search_endpoint="https://search.example.com/")
    original = call(value)
    try:
        resolved, = gateway.resolve_model_tool_calls((original,))
        assert resolved is original
        with pytest.raises(WebSearchInputError):
            parse_web_search_input(resolved.arguments)
        assert LocalPolicyEngine(
            network_profile=parse_network_profile("full-gateway"),
            web_search_endpoint="https://search.example.com/",
        ).evaluate_tool_call(resolved).decision.value != "allow"
    finally:
        gateway.close()


def test_direct_calls_and_other_tools_keep_original_type_boundary(tmp_path: Path):
    gateway = LocalToolGateway(tmp_path, web_search_endpoint="https://search.example.com/")
    try:
        original = call()
        with pytest.raises(WebSearchInputError):
            parse_web_search_input(original.arguments)
        assert gateway.execute(original).status is ToolCallStatus.FAILED
        assert LocalPolicyEngine(
            network_profile=parse_network_profile("full-gateway"),
            web_search_endpoint="https://search.example.com/",
        ).evaluate_tool_call(original).decision.value != "allow"
        for other in (call(name="command.run"), call(name="mcp.server.search"), call(3)):
            assert gateway.resolve_model_tool_calls((other,))[0] is other
    finally:
        gateway.close()


def test_policy_fact_records_raw_provider_arguments(tmp_path: Path):
    from agent_core.harness.orchestration_events import policy_decision_payload

    gateway = LocalToolGateway(tmp_path, web_search_endpoint="https://search.example.com/")
    try:
        original = call()
        resolved, = gateway.resolve_model_tool_calls((original,))
        policy = LocalPolicyEngine(network_profile=parse_network_profile("full-gateway"),
                                   web_search_endpoint="https://search.example.com/")
        payload = policy_decision_payload(attempt_number=1, tool_call=resolved,
                                          decision=policy.evaluate_tool_call(resolved))
        assert payload["provider_arguments"] == original.arguments
        assert payload["provider_tool_name"] == "web.search"
        assert "limit:5" in payload["scope"]
        unchanged = call(5)
        plain = policy_decision_payload(attempt_number=1, tool_call=unchanged,
                                        decision=policy.evaluate_tool_call(unchanged))
        assert "provider_arguments" not in plain and "provider_tool_name" not in plain
    finally:
        gateway.close()


@pytest.mark.parametrize("normalize,expected_rounds", [(False, 3), (True, 2)])
def test_real_harness_avoids_the_argument_repair_round(tmp_path: Path, normalize, expected_rounds):
    from agent_core.domain.events import EventType
    from agent_core.harness import (
        HarnessLoop,
        HarnessModelStep,
        HarnessTask,
        SingleAttemptOrchestrator,
    )
    from agent_tools.web_search import WebSearchResponse, WebSearchResult

    from tests.agent_core.test_concurrent_tool_batches import _completion

    class Model:
        def __init__(self):
            self.requests = []

        def complete(self, messages, *, tools=()):
            self.requests.append(tuple(messages))
            if len(self.requests) == 1:
                return _completion("Looking up.", call())
            latest = next(m for m in reversed(messages) if m.role is MessageRole.TOOL)
            if latest.metadata.get("tool_status") == "failed":
                corrected = call(5).model_copy(update={"provider_call_id": "wire-2"})
                return _completion("Corrected numeric argument.", corrected)
            return _completion("The release is listed at https://example.com/release.")

    class Transport:
        def execute(self, request):
            assert type(request.limit) is int
            return WebSearchResponse(
                results=(WebSearchResult("Release", "https://example.com/release", "Release"),),
                provider="fixed", byte_count=7,
            )

    gateway = LocalToolGateway(tmp_path, web_search_endpoint="https://search.example.com/",
                               web_search_transport=Transport())
    from zebra_agent_worker.worker_tool_gateway import WorkerToolGateway

    gateway = WorkerToolGateway(gateway)
    model = Model()
    policy = LocalPolicyEngine(network_profile=parse_network_profile("full-gateway"),
                               web_search_endpoint="https://search.example.com/")
    try:
        result = HarnessLoop().run(
            HarnessTask(title="Lookup", user_input="Read the input.", max_model_calls=3),
            SingleAttemptOrchestrator(
                model, policy, gateway, synthesize_tool_results=True,
                model_step=HarnessModelStep(available_tools=gateway.model_tools),
                tool_call_resolver=gateway.resolve_model_tool_calls if normalize else None,
            ).run,
        )
        assert result.attempt_result.outcome.value == "completed"
        assert len(model.requests) == expected_rounds
        assert sum(e.event_type is EventType.TOOL_EXECUTION_COMPLETED for e in result.events) == 1
        assert sum(e.event_type is EventType.TOOL_EXECUTION_FAILED for e in result.events) == (
            0 if normalize else 1)
        if normalize:
            fact = next(e for e in result.events if e.event_type is EventType.POLICY_DECISION_MADE)
            assert fact.payload["provider_arguments"]["limit"] == "5"
            proposed = next(
                e for e in result.events if e.event_type is EventType.TOOL_CALL_PROPOSED)
            assert proposed.payload["arguments"]["limit"] == 5
    finally:
        gateway.close()


def test_normalization_cannot_bypass_authority_or_input_checks(tmp_path: Path):
    gateway = LocalToolGateway(tmp_path, web_search_endpoint="https://search.example.com/")
    try:
        resolved, = gateway.resolve_model_tool_calls((call(),))
        assert LocalPolicyEngine().evaluate_tool_call(resolved).decision.value == "deny"
        allowed = LocalPolicyEngine(network_profile=parse_network_profile("full-gateway"),
                                    web_search_endpoint="https://search.example.com/")
        for arguments in ({"query": "", "limit": "5"},
                          {"query": "release", "limit": "5", "extra": True}):
            invalid = call().model_copy(update={"arguments": arguments})
            normalized, = gateway.resolve_model_tool_calls((invalid,))
            assert allowed.evaluate_tool_call(normalized).decision.value == "deny"
        existing = call().model_copy(update={"provider_tool_name": "existing.bridge",
                                             "provider_arguments": {"original": "value"}})
        assert gateway.resolve_model_tool_calls((existing,))[0] is existing
    finally:
        gateway.close()
