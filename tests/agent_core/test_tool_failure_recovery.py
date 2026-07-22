"""Regression tests for HAR-TOOL-RECOVERY-01.

Covers the core invariant: a single ``ToolCallStatus.FAILED`` must not directly
produce a session-level terminal failure. The harness should surface the
failure as an observation, let the model self-correct, and only hard-stop on
explicit harness control signals (loop guard threshold, policy, budget).

Also covers the provider protocol firewall that rejects structurally invalid
message lists before they reach the model gateway.
"""

from datetime import UTC, datetime

import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_core.harness.protocol_invariants import (
    HarnessInvariantError,
    validate_tool_call_pairing,
)

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
TOOLS = (
    ModelToolDefinition(
        name="files.read",
        description="Read a file.",
        parameters={"type": "object", "properties": {}},
    ),
    ModelToolDefinition(
        name="tests.run",
        description="Run tests.",
        parameters={"type": "object", "properties": {}},
    ),
    ModelToolDefinition(
        name="web.fetch",
        description="Fetch a URL.",
        parameters={"type": "object", "properties": {}},
    ),
)


class AllowAllPolicy:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed",
            policy_profile="test",
        )


class RecordingToolGateway:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=f"result:{tool_call.name}",
        )


class FailingToolGateway:
    """Returns FAILED for a named tool; EXECUTED for everything else."""

    def __init__(
        self,
        fail_name: str,
        *,
        reason: str = "http_error",
        detail: str = "HTTP 404",
    ) -> None:
        self._fail_name = fail_name
        self._reason = reason
        self._detail = detail
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        if tool_call.name == self._fail_name:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                metadata={"reason": self._reason, "detail": self._detail},
            )
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=f"result:{tool_call.name}",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _gateway(*completions: ModelCompletion) -> ScriptedModelGateway:
    return ScriptedModelGateway(
        responses=tuple(ScriptedModelResponse(completion=c) for c in completions)
    )


def _call(name: str, arguments: dict[str, object], call_id: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=NOW,
        provider_call_id=call_id,
    )


def _run(
    gateway: ScriptedModelGateway,
    tools: RecordingToolGateway | FailingToolGateway,
    *,
    max_model_calls: int = 5,
    max_tool_calls: int = 5,
):
    return HarnessLoop().run(
        HarnessTask(
            title="Recovery task",
            user_input="Do the work.",
            max_model_calls=max_model_calls,
            max_tool_calls=max_tool_calls,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )


# ---------------------------------------------------------------------------
# Sequential batch: failure should not stop the batch
# ---------------------------------------------------------------------------


def test_sequential_batch_continues_after_first_failure() -> None:
    """A FAILED tool in the middle of a sequential batch must not skip the tail."""
    first = _call("files.read", {"path": "a.txt"}, "call_a")
    failing = _call("tests.run", {"preset": "unit"}, "call_b")
    tail = _call("files.read", {"path": "c.txt"}, "call_c")
    gateway = _gateway(
        _completion("Run the batch.", first, failing, tail),
        _completion("Done after partial failure."),
    )
    tools = FailingToolGateway("tests.run")

    result = _run(gateway, tools)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    # All three calls executed despite the middle failure.
    assert [c.name for c in tools.calls] == ["files.read", "tests.run", "files.read"]
    assert result.attempt_result.metadata["recoverable_tool_failure_count"] == 1
    assert result.attempt_result.metadata["last_failed_tool_name"] == "tests.run"


def test_sequential_batch_all_failed_returns_to_model() -> None:
    """Even when every tool in a batch fails, the model gets a follow-up turn."""
    first = _call("tests.run", {"preset": "a"}, "call_a")
    second = _call("tests.run", {"preset": "b"}, "call_b")
    gateway = _gateway(
        _completion("Run the batch.", first, second),
        _completion("Recovered from total failure."),
    )
    tools = FailingToolGateway("tests.run")

    result = _run(gateway, tools)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["recoverable_tool_failure_count"] == 2


def test_http_404_returns_to_model_for_correction() -> None:
    """End-to-end: a web.fetch returning 404 FAILED lets the model try again.

    This reproduces the motivating scenario: fetching README.md returns 404,
    the model sees the structured observation, and corrects to SKILL.md.
    """
    bad_url = _call("web.fetch", {"url": "https://example.com/README.md"}, "call_bad")
    good_url = _call("web.fetch", {"url": "https://example.com/SKILL.md"}, "call_good")
    gateway = _gateway(
        _completion("Fetch the README.", bad_url),
        _completion("Fetch the SKILL instead.", good_url),
        _completion("Got the content."),
    )
    tools = FailingToolGateway("web.fetch")

    result = _run(gateway, tools, max_tool_calls=3)

    # The session completes despite the initial 404 — the model self-corrected.
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.run_result.tool_calls_used == 2
    # The second call used a different URL (different fingerprint).
    assert tools.calls[0].arguments["url"] != tools.calls[1].arguments["url"]


# ---------------------------------------------------------------------------
# Loop guard: repeated calls become observations, then hard-stop at threshold
# ---------------------------------------------------------------------------


def test_repeated_call_becomes_observation_not_terminal() -> None:
    """The first repeat of a tool call yields a FAILED observation, not a terminal stop."""
    first = _call("files.read", {"path": "same.txt"}, "call_one")
    repeated = _call("files.read", {"path": "same.txt"}, "call_two")
    gateway = _gateway(
        _completion("Read it.", first),
        _completion("Read it again.", repeated),
        _completion("Done."),
    )
    tools = RecordingToolGateway()

    result = _run(gateway, tools, max_tool_calls=3)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    # The repeated call was not re-executed.
    assert len(tools.calls) == 1


# ---------------------------------------------------------------------------
# Provider protocol firewall
# ---------------------------------------------------------------------------


def _assistant_message(*tool_calls: ToolCall) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.ASSISTANT,
        content="assistant",
        created_at=NOW,
        tool_calls=tool_calls,
    )


def _tool_message(tool_call_id: str, content: str = "result") -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.TOOL,
        content=content,
        created_at=NOW,
        tool_call_id=tool_call_id,
    )


def _user_message(content: str = "user") -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content=content,
        created_at=NOW,
    )


def test_protocol_firewall_accepts_well_paired_messages() -> None:
    call = _call("files.read", {"path": "a.txt"}, "call_a")
    messages = [
        _user_message(),
        _assistant_message(call),
        _tool_message("call_a"),
    ]
    validate_tool_call_pairing(messages)  # must not raise


def test_protocol_firewall_rejects_orphan_tool_result() -> None:
    messages = [
        _user_message(),
        _tool_message("call_ghost"),  # no preceding assistant tool_call
    ]
    with pytest.raises(HarnessInvariantError, match="orphan result"):
        validate_tool_call_pairing(messages)


def test_protocol_firewall_rejects_unpaired_tool_call() -> None:
    call = _call("files.read", {"path": "a.txt"}, "call_a")
    messages = [
        _user_message(),
        _assistant_message(call),
        # missing tool result for call_a
    ]
    with pytest.raises(HarnessInvariantError, match="dangling calls"):
        validate_tool_call_pairing(messages)


def test_protocol_firewall_rejects_duplicate_tool_call_id() -> None:
    call_a = _call("files.read", {"path": "a.txt"}, "call_a")
    call_a_repeat = _call("files.read", {"path": "b.txt"}, "call_a")
    messages = [
        _user_message(),
        _assistant_message(call_a, call_a_repeat),  # same provider_call_id
    ]
    with pytest.raises(HarnessInvariantError, match="duplicate tool_call id"):
        validate_tool_call_pairing(messages)


def test_protocol_firewall_rejects_tool_result_before_assistant() -> None:
    """A TOOL message whose tool_call_id has not yet been declared is orphan."""
    call = _call("files.read", {"path": "a.txt"}, "call_a")
    messages = [
        _user_message(),
        _tool_message("call_a"),  # tool result appears before the assistant call
        _assistant_message(call),
    ]
    with pytest.raises(HarnessInvariantError, match="orphan result"):
        validate_tool_call_pairing(messages)
