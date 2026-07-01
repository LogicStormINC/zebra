from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessLoop,
    HarnessTask,
    HarnessTraceProjector,
    SingleAttemptOrchestrator,
)


class AllowAllPolicyEngine:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed in trace test",
            policy_profile="test",
        )


class StaticToolGateway:
    def __init__(self, result: ToolResult) -> None:
        self._result = result

    def execute(self, _tool_call: ToolCall) -> ToolResult:
        return self._result


class ProxyApprovalPolicyEngine:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="proxy-routed trace test",
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


def test_trace_projector_exposes_successful_assistant_and_tool_trace() -> None:
    created_at = datetime(2026, 6, 20, 0, 0, tzinfo=UTC)
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
                        content="I will inspect README.",
                        created_at=created_at,
                    ),
                    tool_calls=(tool_call,),
                )
            ),
        )
    )
    tool_result = ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output="readme body",
        metadata={"path": "README.md"},
    )
    loop = HarnessLoop()
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicyEngine(),
        StaticToolGateway(tool_result),
    )

    result = loop.run(
        HarnessTask(title="Inspect", user_input="Inspect README."),
        orchestrator.run,
        created_at=created_at,
    )
    trace = HarnessTraceProjector().project(result)

    assert len(trace.attempts) == 1
    assert trace.attempts[0].assistant_message == "I will inspect README."
    assert len(trace.attempts[0].tools) == 1
    assert trace.attempts[0].tools[0].tool_name == "files.read"
    assert trace.attempts[0].tools[0].arguments == {"path": "README.md"}
    assert trace.attempts[0].tools[0].status == "executed"
    assert trace.attempts[0].tools[0].output == "readme body"
    assert trace.attempts[0].tools[0].policy_decision == "allow"
    assert trace.attempts[0].tools[0].policy_route is None
    assert trace.attempts[0].tools[0].policy_target is None
    assert trace.attempts[0].tools[0].policy_network_profile is None
    assert trace.attempts[0].tools[0].policy_scope == ()


def test_trace_projector_exposes_failed_tool_trace() -> None:
    created_at = datetime(2026, 6, 20, 0, 5, tzinfo=UTC)
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
                        content="I will run smoke checks.",
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
        metadata={"stderr": "failed"},
    )
    loop = HarnessLoop()
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicyEngine(),
        StaticToolGateway(tool_result),
    )

    result = loop.run(
        HarnessTask(title="Validate", user_input="Run smoke."),
        orchestrator.run,
        created_at=created_at,
    )
    trace = HarnessTraceProjector().project(result)

    assert trace.attempts[0].assistant_message == "I will run smoke checks."
    assert trace.attempts[0].tools[0].tool_name == "tests.run"
    assert trace.attempts[0].tools[0].status == "failed"
    assert trace.attempts[0].tools[0].metadata == {"stderr": "failed"}


def test_trace_projector_normalizes_proxy_policy_metadata() -> None:
    created_at = datetime(2026, 6, 29, 10, 0, tzinfo=UTC)
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
                        content="I will use the proxy path.",
                        created_at=created_at,
                    ),
                    tool_calls=(tool_call,),
                )
            ),
        )
    )
    tool_result = ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output="proxy ok",
        metadata={
            "route": "proxy",
            "proxy_target": "github.create_pull_request",
            "proxy_transport": "mcp_proxy",
        },
    )
    loop = HarnessLoop()
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        ProxyApprovalPolicyEngine(),
        StaticToolGateway(tool_result),
    )

    result = loop.run(
        HarnessTask(title="Proxy trace", user_input="Use MCP proxy."),
        orchestrator.run,
        created_at=created_at,
    )
    trace = HarnessTraceProjector().project(result)
    tool = trace.attempts[0].tools[0]

    assert tool.policy_decision == "allow"
    assert tool.policy_route == "mcp_proxy"
    assert tool.policy_target == "github.create_pull_request"
    assert tool.policy_network_profile == "mcp-proxy-only"
    assert tool.policy_scope == (
        "tool:mcp.github.create_pull_request",
        "route:mcp_proxy",
        "network_profile:mcp-proxy-only",
        "target:github.create_pull_request",
    )
