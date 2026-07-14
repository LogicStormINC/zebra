from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCallMetadata, ModelCompletion, ModelUsage
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    FirstToolCallSelectionStrategy,
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessTask,
    SingleAttemptOrchestrator,
)


class AllowAllPolicyEngine:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed in test",
            policy_profile="test",
        )


class RequireApprovalPolicyEngine:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.REQUIRE_APPROVAL,
            reason="manual approval required in test",
            policy_profile="workspace_write",
        )


class ProxyApprovalPolicyEngine:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.REQUIRE_APPROVAL,
            reason="proxy-routed external tool execution in test",
            policy_profile="full_access",
            route="mcp_proxy",
            target="github.create_pull_request",
            network_profile="mcp-proxy-only",
            scope=(
                "tool:mcp.github.create_pull_request",
                "route:mcp_proxy",
                "network_profile:mcp-proxy-only",
                "target:github.create_pull_request",
            ),
        )


class StaticToolGateway:
    def __init__(self, result: ToolResult) -> None:
        self._result = result
        self.executed_tool_call: ToolCall | None = None

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.executed_tool_call = tool_call
        return self._result


def test_single_attempt_orchestrator_runs_model_to_tool_success_path() -> None:
    created_at = datetime(2026, 6, 19, 22, 0, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "README.md"},
        created_at=created_at,
    )
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="I will inspect the README.",
                        created_at=created_at,
                    ),
                    tool_calls=(tool_call,),
                    call_metadata=ModelCallMetadata(
                        provider="openai",
                        model_name="gpt-5-codex",
                        latency_ms=850,
                        cache_hit=False,
                        cost_usd=0.024,
                        usage=ModelUsage(
                            input_tokens=120,
                            output_tokens=36,
                            total_tokens=156,
                        ),
                    ),
                )
            ),
        )
    )
    tool_result = ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output="readme contents",
        metadata={"path": "README.md"},
    )
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicyEngine(),
        StaticToolGateway(tool_result),
    )
    loop = HarnessLoop()

    result = loop.run(
        HarnessTask(title="Inspect README", user_input="Read the README first."),
        orchestrator.run,
        created_at=created_at,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.session.status.value == "completed"
    assert result.attempt_result.metadata["tool_status"] == "executed"
    assert result.events[4].payload["provider"] == "openai"
    assert result.events[4].payload["model_name"] == "gpt-5-codex"
    assert result.events[4].payload["total_tokens"] == 156
    assert [event.event_type for event in result.events] == [
        EventType.SESSION_CREATED,
        EventType.USER_MESSAGE_RECEIVED,
        EventType.TASK_PREPARED,
        EventType.HARNESS_ATTEMPT_STARTED,
        EventType.MODEL_RESPONSE_RECEIVED,
        EventType.PLAN_PROPOSED,
        EventType.TOOL_CALL_PROPOSED,
        EventType.POLICY_DECISION_MADE,
        EventType.TOOL_EXECUTION_STARTED,
        EventType.TOOL_EXECUTION_COMPLETED,
        EventType.TESTS_COMPLETED,
        EventType.SESSION_COMPLETED,
    ]


def test_single_attempt_orchestrator_synthesizes_tool_result_when_enabled() -> None:
    created_at = datetime(2026, 6, 19, 22, 3, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "proof.txt"},
        created_at=created_at,
        provider_call_id="call_proof",
    )
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Reading the proof.",
                        created_at=created_at,
                    ),
                    tool_calls=(tool_call,),
                )
            ),
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="The proof says zebra-ready.",
                        created_at=created_at,
                    )
                )
            ),
        )
    )
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicyEngine(),
        StaticToolGateway(
            ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.EXECUTED,
                output="zebra-ready",
            )
        ),
        synthesize_tool_results=True,
    )

    result = HarnessLoop().run(
        HarnessTask(
            title="Read proof",
            user_input="Read proof.txt.",
            max_model_calls=2,
        ),
        orchestrator.run,
        created_at=created_at,
    )

    assert result.attempt_result.metadata["assistant_message"] == (
        "The proof says zebra-ready."
    )
    assert result.run_result.model_calls_used == 2
    assert [message.role for message in gateway.requests[1]] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.USER,
    ]
    assert gateway.requests[1][-2].tool_call_id == "call_proof"
    assert gateway.requests[1][-2].content == "zebra-ready"
    assert "Do not request or invoke another tool" in gateway.requests[1][-1].content
    model_events = [
        event for event in result.events if event.event_type is EventType.MODEL_RESPONSE_RECEIVED
    ]
    assert len(model_events) == 2
    assert model_events[-1].payload["response_stage"] == "final"


def test_single_attempt_orchestrator_marks_failed_tool_execution() -> None:
    created_at = datetime(2026, 6, 19, 22, 5, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="tests.run",
        arguments={"preset": "smoke"},
        created_at=created_at,
    )
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="I will run the smoke checks.",
                        created_at=created_at,
                    ),
                    tool_calls=(tool_call,),
                )
            ),
        )
    )
    tool_result = ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.FAILED,
        output="",
        metadata={"stderr": "failure"},
    )
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicyEngine(),
        StaticToolGateway(tool_result),
    )
    loop = HarnessLoop()

    result = loop.run(
        HarnessTask(title="Run smoke", user_input="Run smoke checks."),
        orchestrator.run,
        created_at=created_at,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.session.status.value == "failed"
    assert result.attempt_result.metadata["tool_status"] == "failed"
    assert result.events[-3].event_type is EventType.TOOL_EXECUTION_FAILED
    assert result.events[-2].event_type is EventType.TESTS_COMPLETED
    assert result.events[-1].event_type is EventType.SESSION_FAILED


def test_single_attempt_orchestrator_emits_approval_requested_event() -> None:
    created_at = datetime(2026, 6, 19, 22, 8, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="command.run",
        arguments={"command": ["python", "-m", "pytest"]},
        created_at=created_at,
    )
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="I will run tests.",
                        created_at=created_at,
                    ),
                    tool_calls=(tool_call,),
                )
            ),
        )
    )
    tool_gateway = StaticToolGateway(
        ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
        )
    )
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        RequireApprovalPolicyEngine(),
        tool_gateway,
    )
    loop = HarnessLoop()

    result = loop.run(
        HarnessTask(title="Run tests", user_input="Run pytest."),
        orchestrator.run,
        created_at=created_at,
    )

    assert result.attempt_result.summary == "tool call requires approval"
    assert result.attempt_result.metadata["policy_decision"] == "require_approval"
    assert result.session.status.value == "waiting_approval"
    assert result.run_result.stop_reason.value == "approval_required"
    assert tool_gateway.executed_tool_call is None
    approval_event = next(
        event
        for event in result.events
        if event.event_type is EventType.APPROVAL_REQUESTED
    )
    assert approval_event.payload == {
        "attempt_number": 1,
        "reason": "manual approval required in test",
        "policy_profile": "workspace_write",
        "tool_name": "command.run",
        "arguments": tool_call.arguments,
        "tool_call_id": str(tool_call.tool_call_id),
        "assistant_message": "I will run tests.",
        "call_fingerprint": tool_call.approval_fingerprint,
    }
    assert EventType.TOOL_EXECUTION_STARTED not in [
        event.event_type for event in result.events
    ]


def test_single_attempt_orchestrator_projects_proxy_approval_metadata() -> None:
    created_at = datetime(2026, 6, 28, 14, 0, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="mcp.github.create_pull_request",
        arguments={"title": "Add feature"},
        created_at=created_at,
    )
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="I will route the MCP call through the proxy path.",
                        created_at=created_at,
                    ),
                    tool_calls=(tool_call,),
                )
            ),
        )
    )
    tool_gateway = StaticToolGateway(
        ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
        )
    )
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        ProxyApprovalPolicyEngine(),
        tool_gateway,
    )
    loop = HarnessLoop()

    result = loop.run(
        HarnessTask(title="Proxy approval", user_input="Use the MCP proxy."),
        orchestrator.run,
        created_at=created_at,
    )

    policy_event = next(
        event
        for event in result.events
        if event.event_type is EventType.POLICY_DECISION_MADE
    )
    approval_event = next(
        event
        for event in result.events
        if event.event_type is EventType.APPROVAL_REQUESTED
    )

    assert result.attempt_result.summary == "tool call requires approval"
    assert result.attempt_result.metadata["policy_decision"] == "require_approval"
    assert tool_gateway.executed_tool_call is None
    assert policy_event.payload == {
        "attempt_number": 1,
        "decision": "require_approval",
        "reason": "proxy-routed external tool execution in test",
        "policy_profile": "full_access",
        "tool_name": "mcp.github.create_pull_request",
        "route": "mcp_proxy",
        "target": "github.create_pull_request",
        "network_profile": "mcp-proxy-only",
        "scope": [
            "tool:mcp.github.create_pull_request",
            "route:mcp_proxy",
            "network_profile:mcp-proxy-only",
            "target:github.create_pull_request",
        ],
    }
    assert approval_event.payload == {
        "attempt_number": 1,
        "reason": "proxy-routed external tool execution in test",
        "policy_profile": "full_access",
        "tool_name": "mcp.github.create_pull_request",
        "arguments": tool_call.arguments,
        "tool_call_id": str(tool_call.tool_call_id),
        "assistant_message": "I will route the MCP call through the proxy path.",
        "call_fingerprint": tool_call.approval_fingerprint,
        "route": "mcp_proxy",
        "target": "github.create_pull_request",
        "network_profile": "mcp-proxy-only",
        "scope": [
            "tool:mcp.github.create_pull_request",
            "route:mcp_proxy",
            "network_profile:mcp-proxy-only",
            "target:github.create_pull_request",
        ],
    }


def test_first_tool_call_selection_strategy_is_deterministic() -> None:
    created_at = datetime(2026, 6, 19, 22, 10, tzinfo=UTC)
    first_tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "README.md"},
        created_at=created_at,
    )
    second_tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="tests.run",
        arguments={"preset": "smoke"},
        created_at=created_at,
    )

    selection = FirstToolCallSelectionStrategy().select(
        (first_tool_call, second_tool_call)
    )

    assert selection.tool_call == first_tool_call
    assert selection.summary == "selected first tool call"
    assert selection.metadata == {
        "selected_index": 0,
        "candidate_count": 2,
    }


def test_single_attempt_orchestrator_uses_selected_tool_call_from_multi_tool_completion() -> None:
    created_at = datetime(2026, 6, 19, 22, 15, tzinfo=UTC)
    first_tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "README.md"},
        created_at=created_at,
    )
    second_tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="tests.run",
        arguments={"preset": "smoke"},
        created_at=created_at,
    )
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="I will inspect the README before running checks.",
                        created_at=created_at,
                    ),
                    tool_calls=(first_tool_call, second_tool_call),
                )
            ),
        )
    )
    tool_result = ToolResult(
        tool_call_id=first_tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output="readme contents",
        metadata={"path": "README.md"},
    )
    tool_gateway = StaticToolGateway(tool_result)
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicyEngine(),
        tool_gateway,
    )
    loop = HarnessLoop()

    result = loop.run(
        HarnessTask(title="Inspect README", user_input="Read before running checks."),
        orchestrator.run,
        created_at=created_at,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert tool_gateway.executed_tool_call == first_tool_call
    assert result.attempt_result.metadata["tool_name"] == "files.read"
    assert result.attempt_result.metadata["tool_selection_summary"] == (
        "selected first tool call"
    )
    assert result.attempt_result.metadata["tool_selection_metadata"] == {
        "selected_index": 0,
        "candidate_count": 2,
    }
    assert result.events[6].payload["tool_name"] == "files.read"
    assert result.events[6].payload["selection_summary"] == "selected first tool call"
    assert result.events[6].payload["selection_metadata"] == {
        "selected_index": 0,
        "candidate_count": 2,
    }
