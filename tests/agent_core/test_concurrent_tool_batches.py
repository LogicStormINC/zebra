from datetime import UTC, datetime
from threading import Barrier, Lock

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
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)

NOW = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
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
)


class PolicyByProviderId:
    def __init__(self, denied_id: str | None = None) -> None:
        self._denied_id = denied_id

    def evaluate_tool_call(self, tool_call: ToolCall) -> PolicyDecision:
        denied = tool_call.provider_call_id == self._denied_id
        return PolicyDecision(
            decision=PolicyDecisionType.DENY if denied else PolicyDecisionType.ALLOW,
            reason="denied in test" if denied else "allowed in test",
            policy_profile="test",
        )


class ProbeGateway:
    def __init__(self, *, pair_size: int = 2, failed_id: str | None = None) -> None:
        self._barrier = Barrier(pair_size)
        self._failed_id = failed_id
        self._lock = Lock()
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0

    def execute(self, tool_call: ToolCall) -> ToolResult:
        with self._lock:
            self.calls.append(tool_call.provider_call_id or "")
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self._barrier.wait(timeout=2)
        finally:
            with self._lock:
                self.active -= 1
        failed = tool_call.provider_call_id == self._failed_id
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.FAILED if failed else ToolCallStatus.EXECUTED,
            output=f"result:{tool_call.provider_call_id}",
        )


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=f"result:{tool_call.provider_call_id}",
        )


def test_parallel_safe_calls_overlap_and_preserve_provider_order() -> None:
    calls = (_read("a.txt", "call_a"), _read("b.txt", "call_b"))
    tools = ProbeGateway()
    result, model = _run(calls, tools, max_parallel=2)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert tools.max_active == 2
    assert result.attempt_result.metadata["parallel_batch_size"] == 2
    assert [message.tool_call_id for message in model.requests[1][-3:-1]] == [
        "call_a",
        "call_b",
    ]
    assert _event_names(result, EventType.TOOL_EXECUTION_COMPLETED) == [
        "files.read",
        "files.read",
    ]
    expected_ids = [str(call.tool_call_id) for call in calls]
    for event_type in (
        EventType.TOOL_CALL_PROPOSED,
        EventType.POLICY_DECISION_MADE,
        EventType.TOOL_EXECUTION_STARTED,
        EventType.TOOL_EXECUTION_COMPLETED,
    ):
        assert [
            event.payload["tool_call_id"]
            for event in result.events
            if event.event_type is event_type
        ] == expected_ids


def test_parallel_safe_batch_enforces_concurrency_limit() -> None:
    calls = tuple(_read(f"{index}.txt", f"call_{index}") for index in range(4))
    tools = ProbeGateway(pair_size=2)
    result, _ = _run(calls, tools, max_parallel=2)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert tools.max_active == 2
    assert result.run_result.tool_calls_used == 4


def test_mixed_batch_uses_existing_sequential_path() -> None:
    calls = (
        _read("a.txt", "call_a"),
        _call("tests.run", {"preset": "test"}, "call_b"),
    )
    tools = RecordingGateway()
    result, _ = _run(calls, tools, max_parallel=2)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert tools.calls == list(calls)
    assert "parallel_batch_size" not in result.attempt_result.metadata


def test_unknown_capability_uses_existing_sequential_path() -> None:
    calls = (
        _call("external.inspect", {}, "call_external"),
        _read("a.txt", "call_read"),
    )
    tools = RecordingGateway()
    result, _ = _run(calls, tools, max_parallel=2)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert tools.calls == list(calls)
    assert "parallel_batch_size" not in result.attempt_result.metadata


def test_candidate_batch_denial_stops_before_any_tool_starts() -> None:
    calls = (_read("a.txt", "call_a"), _read("b.txt", "call_b"))
    tools = RecordingGateway()
    result, _ = _run(
        calls,
        tools,
        max_parallel=2,
        policy=PolicyByProviderId("call_b"),
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert tools.calls == []
    assert _event_names(result, EventType.TOOL_EXECUTION_STARTED) == []


def test_concurrent_failure_observes_every_started_sibling() -> None:
    calls = (_read("a.txt", "call_a"), _read("b.txt", "call_b"))
    tools = ProbeGateway(failed_id="call_a")
    result, _ = _run(calls, tools, max_parallel=2)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.attempt_result.metadata["stop_reason"] == "concurrent_tool_failure"
    assert result.run_result.tool_calls_used == 2
    assert sorted(tools.calls) == ["call_a", "call_b"]
    assert len(_event_names(result, EventType.TOOL_EXECUTION_STARTED)) == 2
    finished = _event_names(result, EventType.TOOL_EXECUTION_COMPLETED)
    failed = _event_names(result, EventType.TOOL_EXECUTION_FAILED)
    assert len(finished) + len(failed) == 2
    terminal_ids = [
        event.payload["tool_call_id"]
        for event in result.events
        if event.event_type
        in {EventType.TOOL_EXECUTION_COMPLETED, EventType.TOOL_EXECUTION_FAILED}
    ]
    assert terminal_ids == [str(call.tool_call_id) for call in calls]


def test_candidate_batch_budget_rejection_starts_nothing() -> None:
    calls = (_read("a.txt", "call_a"), _read("b.txt", "call_b"))
    tools = RecordingGateway()
    result, _ = _run(calls, tools, max_parallel=2, max_tool_calls=1)

    assert result.attempt_result.metadata["stop_reason"] == "tool_call_budget_exhausted"
    assert tools.calls == []
    assert _event_names(result, EventType.TOOL_EXECUTION_STARTED) == []


def test_candidate_batch_capacity_rejection_starts_nothing() -> None:
    calls = (_read("a.txt", "call_a"), _read("b.txt", "call_b"))
    tools = RecordingGateway()
    result, _ = _run(
        calls,
        tools,
        max_parallel=2,
        parallel_batch_limits={"files.read": 1},
    )

    assert result.attempt_result.metadata["stop_reason"] == (
        "parallel_batch_limit_exceeded"
    )
    assert tools.calls == []
    assert _event_names(result, EventType.TOOL_EXECUTION_STARTED) == []


def test_candidate_batch_duplicate_rejection_starts_nothing() -> None:
    calls = (_read("same.txt", "call_a"), _read("same.txt", "call_b"))
    tools = RecordingGateway()
    result, _ = _run(calls, tools, max_parallel=2)

    assert result.attempt_result.metadata["stop_reason"] == "repeated_tool_call"
    assert tools.calls == []
    assert _event_names(result, EventType.TOOL_EXECUTION_STARTED) == []


def _run(
    calls: tuple[ToolCall, ...],
    tools: ProbeGateway | RecordingGateway,
    *,
    max_parallel: int,
    max_tool_calls: int | None = None,
    parallel_batch_limits: dict[str, int] | None = None,
    policy: PolicyByProviderId | None = None,
):
    model = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(completion=_completion("Use the tools.", *calls)),
            ScriptedModelResponse(completion=_completion("Finished.")),
        )
    )
    result = HarnessLoop().run(
        HarnessTask(
            title="Concurrent batch",
            user_input="Read the inputs.",
            max_model_calls=2,
            max_tool_calls=max_tool_calls or len(calls),
        ),
        SingleAttemptOrchestrator(
            model,
            policy or PolicyByProviderId(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
            parallel_safe_tools=frozenset({"files.read"}),
            parallel_batch_limits=parallel_batch_limits,
            max_parallel_tool_calls=max_parallel,
        ).run,
        created_at=NOW,
    )
    return result, model


def _event_names(result, event_type: EventType) -> list[str]:
    return [event.payload["tool_name"] for event in result.events if event.event_type is event_type]


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


def _read(path: str, provider_id: str) -> ToolCall:
    return _call("files.read", {"path": path}, provider_id)


def _call(name: str, arguments: dict[str, object], provider_id: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=NOW,
        provider_call_id=provider_id,
    )
