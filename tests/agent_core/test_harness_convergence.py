from datetime import UTC, datetime
from threading import Lock

import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventActor, EventType
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
from agent_core.harness.attempt_result import update_batch_observation_progress
from agent_core.harness.models import HarnessEventDraft

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
TOOLS = (
    ModelToolDefinition(
        name="files.read",
        description="Read a fixture.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    ),
)


class AllowAllPolicy:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed",
            policy_profile="test",
        )


class StableEvidenceGateway:
    def __init__(self, evidence_by_query: dict[str, str]) -> None:
        self._evidence_by_query = evidence_by_query
        self._lock = Lock()
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        query = str(tool_call.arguments["query"])
        evidence = self._evidence_by_query[query]
        with self._lock:
            self.calls.append(tool_call)
        output = (
            f'{{"evidence":"{evidence}","source":"fixture"}}'
            if query.endswith(("0", "2", "a"))
            else f'{{"source":"fixture","evidence":"{evidence}"}}'
        )
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=output,
            metadata={
                "artifact_uri": f"artifact://{evidence}",
                "captured_at": tool_call.provider_call_id,
            },
        )


def test_semantic_argument_variants_force_one_tool_disabled_synthesis() -> None:
    calls = tuple(_call(f"variant-{index}") for index in range(4))
    model = _gateway(
        *(_completion("Collect more.", call) for call in calls),
        _completion("Synthesized from the stable evidence."),
    )
    tools = StableEvidenceGateway({str(call.arguments["query"]): "same" for call in calls})

    result = _run(model, tools)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == (
        "Synthesized from the stable evidence."
    )
    assert result.attempt_result.metadata["consecutive_no_progress_batches"] == 3
    assert result.attempt_result.metadata["terminal_synthesis_attempted"] is True
    assert len(tools.calls) == 4
    assert model.tool_requests.count(()) == 1
    assert model.tool_requests[-1] == ()
    assert any(
        message.metadata.get("tool_loop_no_progress") is True
        for message in model.requests[-1]
        if message.role is MessageRole.USER
    )


def test_terminal_synthesis_suspends_when_model_still_requests_tools() -> None:
    calls = tuple(_call(f"variant-{index}") for index in range(5))
    model = _gateway(*(_completion("Collect more.", call) for call in calls))
    tools = StableEvidenceGateway({str(call.arguments["query"]): "same" for call in calls})

    result = _run(model, tools)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == "tool_loop_no_progress"
    assert result.attempt_result.metadata["terminal_synthesis_attempted"] is True
    assert len(tools.calls) == 4
    assert model.tool_requests[-1] == ()
    assert result.events[-1].event_type is EventType.SESSION_SUSPENDED


def test_exact_repeat_guard_still_prevents_reexecution_before_synthesis() -> None:
    calls = tuple(_call("same", f"repeat-{index}") for index in range(4))
    model = _gateway(
        *(_completion("Read it again.", call) for call in calls),
        _completion("The original evidence is sufficient."),
    )
    tools = StableEvidenceGateway({"same": "same"})

    result = _run(model, tools)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert len(tools.calls) == 1
    counts = result.attempt_result.metadata["loop_guard_counts"]
    assert isinstance(counts, dict) and list(counts.values()) == [2]
    assert model.tool_requests[-1] == ()


def test_new_evidence_resets_progress_counter_and_allows_long_chain() -> None:
    queries = (
        "first",
        "same-a",
        "same-b",
        "new",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
    )
    calls = tuple(_call(query) for query in queries)
    evidence_by_query = {
        "first": "initial",
        "same-a": "initial",
        "same-b": "initial",
        "new": "replacement",
        "five": "five",
        "six": "six",
        "seven": "seven",
        "eight": "eight",
        "nine": "nine",
    }
    model = _gateway(
        *(_completion("Collect the next item.", call) for call in calls),
        _completion("Nine evidence items were considered."),
    )
    tools = StableEvidenceGateway(evidence_by_query)

    result = _run(model, tools)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["consecutive_no_progress_batches"] == 0
    assert result.run_result.tool_calls_used == 9
    assert len(tools.calls) == 9
    assert model.tool_requests.count(()) == 0


@pytest.mark.parametrize(
    ("event_type", "actor"),
    (
        (EventType.PLAN_UPDATED, EventActor.HARNESS),
        (EventType.APPROVAL_REQUESTED, EventActor.POLICY),
    ),
)
def test_auditable_plan_or_approval_state_change_resets_progress(
    event_type: EventType,
    actor: EventActor,
) -> None:
    metadata = update_batch_observation_progress(
        {"consecutive_no_progress_batches": 2},
        (),
        (HarnessEventDraft(event_type=event_type, actor=actor),),
        threshold=3,
    )

    assert metadata["consecutive_no_progress_batches"] == 0
    assert metadata["tool_loop_no_progress"] is False


@pytest.mark.parametrize("max_parallel", (1, 2))
def test_no_progress_convergence_has_sequential_concurrent_batch_parity(
    max_parallel: int,
) -> None:
    batches = tuple(
        (_call(f"batch-{batch}-a"), _call(f"batch-{batch}-b"))
        for batch in range(4)
    )
    calls = tuple(call for batch in batches for call in batch)
    model = _gateway(
        *(_completion("Collect the batch.", *batch) for batch in batches),
        _completion("The repeated evidence is sufficient."),
    )
    tools = StableEvidenceGateway({str(call.arguments["query"]): "same" for call in calls})

    result = _run(model, tools, max_parallel=max_parallel)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["consecutive_no_progress_batches"] == 3
    assert result.attempt_result.metadata["terminal_synthesis_attempted"] is True
    assert len(tools.calls) == 8
    assert model.tool_requests.count(()) == 1


def _run(
    model: ScriptedModelGateway,
    tools: StableEvidenceGateway,
    *,
    max_parallel: int = 1,
):
    return HarnessLoop().run(
        HarnessTask(title="Convergence", user_input="Use the available evidence."),
        SingleAttemptOrchestrator(
            model,
            AllowAllPolicy(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
            parallel_safe_tools=frozenset({"files.read"}),
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


def _call(query: str, provider_suffix: str | None = None) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"query": query},
        created_at=NOW,
        provider_call_id=f"provider-{provider_suffix or query}",
    )
