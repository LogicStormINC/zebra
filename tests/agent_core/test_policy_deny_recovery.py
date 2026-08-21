from datetime import UTC, datetime

import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessLoopResult,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_security import LocalPolicyEngine, PolicyProfile
from agent_security.network_profile import parse_network_profile

NOW = datetime(2026, 7, 29, 16, 0, tzinfo=UTC)
FINAL_MARKER = "SYNTHETIC_TRANSACTION_LOG_COMPLETE"
TOOLS = (
    ModelToolDefinition(
        name="web.fetch",
        description="Fetch a public page.",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}},
    ),
    ModelToolDefinition(
        name="files.read",
        description="Read a workspace file.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
    ),
    ModelToolDefinition(
        name="files.list",
        description="List a workspace root.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1}},
        },
    ),
)


class RecordingTools:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=FINAL_MARKER,
        )


def test_policy_defaults_denies_to_terminal_and_marks_only_web_input_errors() -> None:
    policy = _policy()
    fragment = _fetch("https://docs.example.com/ledger#section", "fragment")
    authority = _fetch("https://unlisted.example.com/ledger", "authority")
    unlisted_fragment = _fetch("https://unlisted.example.com/ledger#section", "unlisted")
    credentials = _fetch("https://token:secret@docs.example.com/ledger", "credentials")
    loopback = _fetch("https://127.0.0.1/ledger", "loopback")
    escape = _call("files.read", {"path": "../secret.txt"}, "escape")
    invalid_search = _call("web.search", {"query": " "}, "invalid-search")
    search_policy = LocalPolicyEngine(
        profile=PolicyProfile.READ_ONLY,
        network_profile=parse_network_profile(
            "domain-allowlist", domain_allowlist=("search.example.com",)
        ),
        web_search_endpoint="https://search.example.com/search",
    )
    endpoint_error_policy = LocalPolicyEngine(
        profile=PolicyProfile.READ_ONLY,
        network_profile=parse_network_profile(
            "domain-allowlist", domain_allowlist=("search.example.com",)
        ),
        web_search_endpoint="http://search.example.com/search",
    )

    assert (
        PolicyDecision(
            decision=PolicyDecisionType.DENY,
            reason="test",
            policy_profile="test",
        ).recoverable
        is False
    )
    assert policy.evaluate_tool_call(fragment).recoverable is True
    assert policy.evaluate_tool_call(fragment).reason == "web URL must not contain a fragment"
    assert policy.evaluate_tool_call(authority).recoverable is False
    assert policy.evaluate_tool_call(unlisted_fragment).recoverable is False
    assert policy.evaluate_tool_call(credentials).recoverable is False
    assert policy.evaluate_tool_call(loopback).recoverable is False
    assert policy.evaluate_tool_call(escape).recoverable is False
    assert search_policy.evaluate_tool_call(invalid_search).recoverable is True
    assert endpoint_error_policy.evaluate_tool_call(invalid_search).recoverable is False


@pytest.mark.parametrize("max_parallel", (1, 2))
def test_fragment_deny_is_observed_then_corrected_without_gateway_call(
    max_parallel: int,
) -> None:
    fragment = _fetch("https://docs.example.com/ledger#section", "fragment")
    sibling = _fetch("https://docs.example.com/unused", "sibling")
    corrected = _fetch("https://docs.example.com/ledger", "corrected")
    policy = _policy()
    expected_deny = policy.evaluate_tool_call(fragment)
    assert expected_deny.reason == "web URL must not contain a fragment"
    model = _gateway(
        _completion("Fetch the source.", fragment, sibling),
        _completion("Correct the URL.", corrected),
        _completion(FINAL_MARKER),
        _completion(FINAL_MARKER),
    )
    tools = RecordingTools()

    result = _run(model, tools, policy=policy, max_parallel=max_parallel)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == FINAL_MARKER
    assert tools.calls == [corrected]
    assert result.run_result.tool_calls_used == 1
    policy_events = [
        event for event in result.events if event.event_type is EventType.POLICY_DECISION_MADE
    ]
    assert policy_events[0].payload["decision"] == "deny"
    assert policy_events[0].payload["reason"] == expected_deny.reason
    failed = [
        event for event in result.events if event.event_type is EventType.TOOL_EXECUTION_FAILED
    ]
    assert len(failed) == 1
    assert failed[0].payload["tool_call_id"] == str(fragment.tool_call_id)
    assert failed[0].payload["metadata"]["executed"] is False
    assert str(fragment.tool_call_id) not in [
        event.payload["tool_call_id"]
        for event in result.events
        if event.event_type is EventType.TOOL_EXECUTION_STARTED
    ]
    observed = next(
        message
        for message in model.requests[1]
        if message.role is MessageRole.TOOL and message.tool_call_id == "fragment"
    )
    assert expected_deny.reason in observed.content


def test_second_recoverable_deny_runs_one_tool_disabled_terminal_synthesis() -> None:
    first = _fetch("https://docs.example.com/ledger#first", "first")
    second = _fetch("https://docs.example.com/ledger#second", "second")
    model = _gateway(
        _completion("Fetch the source.", first),
        _completion("Try another fragment.", second),
        _completion(FINAL_MARKER),
    )
    tools = RecordingTools()

    result = _run(model, tools, policy=_policy(), max_parallel=1)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == FINAL_MARKER
    assert tools.calls == []
    assert result.run_result.attempts_used == 1
    assert model.tool_requests.count(()) == 1
    assert (
        len(
            [
                event
                for event in result.events
                if event.event_type is EventType.TOOL_EXECUTION_FAILED
            ]
        )
        == 2
    )


def test_concurrent_recovery_discards_unexecuted_siblings_before_correction() -> None:
    sibling = _fetch("https://docs.example.com/unused", "sibling")
    fragment = _fetch("https://docs.example.com/ledger#section", "fragment")
    corrected = _fetch("https://docs.example.com/ledger", "corrected")
    model = _gateway(
        _completion("Fetch the source.", sibling, fragment),
        _completion("Correct the URL.", corrected),
        _completion(FINAL_MARKER),
        _completion(FINAL_MARKER),
    )
    tools = RecordingTools()

    result = _run(model, tools, policy=_policy(), max_parallel=2)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert tools.calls == [corrected]
    assistant_batch = next(
        message
        for message in model.requests[1]
        if message.role is MessageRole.ASSISTANT and message.tool_calls
    )
    assert [call.provider_call_id for call in assistant_batch.tool_calls] == ["fragment"]


def test_unmarked_workspace_escape_deny_stays_terminal() -> None:
    escape = _call("files.read", {"path": "../secret.txt"}, "escape")
    model = _gateway(_completion("Read the file.", escape))
    tools = RecordingTools()

    result = _run(model, tools, policy=_policy(), max_parallel=1)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert tools.calls == []
    assert len(model.requests) == 1


def test_blank_workspace_root_deny_is_observed_then_corrected_in_one_attempt() -> None:
    blank = _call("files.list", {"path": ""}, "blank")
    sibling = _call("files.list", {"path": "unused"}, "sibling")
    corrected = _call("files.list", {}, "corrected")
    policy = _policy()
    expected_deny = policy.evaluate_tool_call(blank)
    model = _gateway(
        _completion("List the workspace.", blank, sibling),
        _completion("Use the default workspace root.", corrected),
        _completion(FINAL_MARKER),
    )
    tools = RecordingTools()

    result = _run(
        model,
        tools,
        policy=policy,
        max_parallel=1,
        max_model_calls=3,
    )

    assert expected_deny.recoverable is True
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.run_result.attempts_used == 1
    assert len(model.requests) == 3
    assert result.run_result.tool_calls_used == 1
    assert tools.calls == [corrected]
    assert expected_deny.reason in next(
        message.content
        for message in model.requests[1]
        if message.role is MessageRole.TOOL and message.tool_call_id == "blank"
    )
    retained_batch = next(
        message
        for message in model.requests[1]
        if message.role is MessageRole.ASSISTANT and message.tool_calls
    )
    assert [call.provider_call_id for call in retained_batch.tool_calls] == ["blank"]
    assert {
        event.payload["tool_call_id"]
        for event in result.events
        if event.event_type is EventType.TOOL_EXECUTION_STARTED
    } == {str(corrected.tool_call_id)}


def test_unlisted_fragment_deny_stays_terminal() -> None:
    fragment = _fetch("https://unlisted.example.com/ledger#section", "unlisted")
    model = _gateway(_completion("Fetch the source.", fragment))
    tools = RecordingTools()

    result = _run(model, tools, policy=_policy(), max_parallel=1)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert tools.calls == []
    assert len(model.requests) == 1


def _policy() -> LocalPolicyEngine:
    return LocalPolicyEngine(
        profile=PolicyProfile.READ_ONLY,
        network_profile=parse_network_profile(
            "domain-allowlist", domain_allowlist=("docs.example.com",)
        ),
    )


def _run(
    model: ScriptedModelGateway,
    tools: RecordingTools,
    *,
    policy: LocalPolicyEngine,
    max_parallel: int,
    max_model_calls: int | None = None,
) -> HarnessLoopResult:
    return HarnessLoop().run(
        HarnessTask(
            title="Policy recovery",
            user_input="Produce the synthetic log.",
            max_model_calls=max_model_calls,
        ),
        SingleAttemptOrchestrator(
            model,
            policy,
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
            parallel_safe_tools=frozenset({"web.fetch"}),
            max_parallel_tool_calls=max_parallel,
        ).run,
        created_at=NOW,
    )


def _gateway(*completions: ModelCompletion) -> ScriptedModelGateway:
    return ScriptedModelGateway(
        responses=tuple(ScriptedModelResponse(completion=completion) for completion in completions)
    )


def _completion(content: str, *tool_calls: ToolCall) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=NOW,
        ),
        tool_calls=tool_calls,
    )


def _fetch(url: str, provider_call_id: str) -> ToolCall:
    return _call("web.fetch", {"url": url}, provider_call_id)


def _call(name: str, arguments: dict[str, object], provider_call_id: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=NOW,
        provider_call_id=provider_call_id,
    )
