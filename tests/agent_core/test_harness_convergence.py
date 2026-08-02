from datetime import UTC, datetime
from threading import Lock

import pytest
from agent_context.conversation import compact_message_history
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
    HarnessStopReason,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_core.harness.attempt_result import (
    append_no_progress_observation,
    observation_fingerprint,
    update_batch_observation_progress,
)
from agent_core.harness.models import HarnessEventDraft
from agent_tools.output_projection import ToolOutputProjector

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


class ApprovalOnCommandPolicy(AllowAllPolicy):
    def evaluate_tool_call(self, tool_call: ToolCall) -> PolicyDecision:
        if tool_call.name == "command.run":
            return PolicyDecision(
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                reason="approval required",
                policy_profile="test",
            )
        return super().evaluate_tool_call(tool_call)


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
        if message.role is MessageRole.SYSTEM
    )
    terminal_instruction = next(
        message.content
        for message in model.requests[-1]
        if message.metadata.get("tool_loop_no_progress") is True
    )
    assert "complete, self-contained final answer" in terminal_instruction
    assert "not merely refer to earlier or intermediate output" in terminal_instruction
    assert sum(
        message.content.startswith("The tool budget is complete.")
        for message in model.requests[-1]
        if message.role is MessageRole.USER
    ) == 1


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
    assert result.run_result.stop_reason is HarnessStopReason.TOOL_LOOP_NO_PROGRESS


@pytest.mark.parametrize(
    "boilerplate",
    ("", "Tool calls proposed.\n\n", "说明：我还需要一次查询。\n\n"),
    ids=("bare", "provider-boilerplate", "ordinary-explanation"),
)
def test_terminal_synthesis_suspends_for_raw_dsml_tool_request(boilerplate: str) -> None:
    calls = tuple(_call(f"variant-{index}") for index in range(4))
    raw_dsml = (
        boilerplate
        + "<｜｜DSML｜｜tool_calls>\n"
        "<｜｜DSML｜｜invoke name=\"web__fetch\">\n"
        "<｜｜DSML｜｜parameter name=\"url\" string=\"https://example.test\" />\n"
        "</｜｜DSML｜｜invoke>\n"
        "</｜｜DSML｜｜tool_calls>"
    )
    model = _gateway(
        *(_completion("Collect more.", call) for call in calls),
        _completion(raw_dsml),
    )
    tools = StableEvidenceGateway({str(call.arguments["query"]): "same" for call in calls})

    result = _run(model, tools)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == "tool_loop_no_progress"
    assert result.attempt_result.metadata["assistant_message"] == raw_dsml
    assert result.attempt_result.metadata["terminal_synthesis_attempted"] is True
    assert result.run_result.stop_reason is HarnessStopReason.TOOL_LOOP_NO_PROGRESS
    assert len(tools.calls) == 4
    assert model.tool_requests.count(()) == 1
    assert model.tool_requests[-1] == ()


def test_terminal_synthesis_suspends_for_unfenced_dsml_after_a_fenced_example() -> None:
    calls = tuple(_call(f"variant-{index}") for index in range(4))
    raw_dsml = (
        "```xml\n"
        "<｜｜DSML｜｜tool_calls>\n"
        "<｜｜DSML｜｜invoke name=\"web__fetch\">\n"
        "```\n"
        "说明：上面只是示例；下面仍要调用工具。\n"
        "<｜｜DSML｜｜tool_calls>\n"
        "<｜｜DSML｜｜invoke name=\"web__fetch\">\n"
        "<｜｜DSML｜｜parameter name=\"url\" string=\"https://example.test\" />\n"
        "</｜｜DSML｜｜invoke>\n"
        "</｜｜DSML｜｜tool_calls>"
    )
    model = _gateway(
        *(_completion("Collect more.", call) for call in calls),
        _completion(raw_dsml),
    )
    tools = StableEvidenceGateway({str(call.arguments["query"]): "same" for call in calls})

    result = _run(model, tools)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == "tool_loop_no_progress"


def test_terminal_synthesis_keeps_regular_text_that_mentions_dsml() -> None:
    calls = tuple(_call(f"variant-{index}") for index in range(4))
    explanation = (
        "Tool calls proposed.\n\n"
        "```text\n"
        "<｜｜DSML｜｜tool_calls>\n"
        "<｜｜DSML｜｜invoke name=\"web__fetch\">\n"
        "```\n"
        "This is documentation, not a request to call a tool."
    )
    model = _gateway(
        *(_completion("Collect more.", call) for call in calls),
        _completion(explanation),
    )
    tools = StableEvidenceGateway({str(call.arguments["query"]): "same" for call in calls})

    result = _run(model, tools)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == explanation
    assert model.tool_requests[-1] == ()


def test_projected_output_fingerprint_ignores_ephemeral_artifact_uri() -> None:
    uris = iter(("artifact://run-1", "artifact://run-2"))
    projector = ToolOutputProjector(
        lambda _content, _name: next(uris),
        max_model_characters=256,
    )
    content = "same projected output " * 32
    first = projector.project_text(content, artifact_name="first.txt")
    second = projector.project_text(content, artifact_name="second.txt")

    first_result = ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output=first.model_output,
        metadata=first.metadata,
    )
    second_result = ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output=second.model_output,
        metadata=second.metadata,
    )

    assert observation_fingerprint(_call("first"), first_result) == observation_fingerprint(
        _call("second"), second_result
    )


def test_mixed_batch_keeps_new_calls_plan_and_approval_audit_after_repeat() -> None:
    first = _call("same", "first")
    repeated = tuple(_call("same", f"repeat-{index}") for index in range(3))
    mixed_repeat = _call("same", "repeat-mixed")
    reset = _call("reset", "reset")
    fresh = _call("fresh", "fresh")
    plan = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.plan",
        arguments={
            "steps": [
                {
                    "step_id": "answer",
                    "content": "Prepare the answer",
                    "status": "in_progress",
                }
            ]
        },
        created_at=NOW,
        provider_call_id="plan",
    )
    approval = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="command.run",
        arguments={"command": ["echo", "approved"]},
        created_at=NOW,
        provider_call_id="approval",
    )
    model = _gateway(
        _completion("Read the baseline.", first),
        _completion("Read it again.", repeated[0]),
        _completion("Read it again.", repeated[1]),
        _completion("Get a different result.", reset),
        _completion("Read it again.", repeated[2]),
        _completion("Continue the mixed batch.", mixed_repeat, fresh, plan, approval),
        _completion("Synthesize if no batch is allowed."),
    )
    tools = StableEvidenceGateway({"same": "same", "reset": "reset", "fresh": "fresh"})

    result = _run(model, tools, policy=ApprovalOnCommandPolicy())

    assert result.attempt_result.outcome is HarnessAttemptOutcome.WAITING_APPROVAL
    assert tools.calls == [first, reset, fresh]
    mixed_ids = {str(call.tool_call_id) for call in (mixed_repeat, fresh, plan, approval)}
    proposed_ids = {
        str(event.payload["tool_call_id"])
        for event in result.events
        if event.event_type is EventType.TOOL_CALL_PROPOSED
    }
    audited_ids = {
        str(event.payload["tool_call_id"])
        for event in result.events
        if event.event_type is EventType.POLICY_DECISION_MADE
    }
    assert mixed_ids <= proposed_ids
    assert {str(call.tool_call_id) for call in (fresh, plan, approval)} <= audited_ids
    assert any(event.event_type is EventType.PLAN_UPDATED for event in result.events)
    assert any(event.event_type is EventType.APPROVAL_REQUESTED for event in result.events)


def test_concurrent_mixed_batch_executes_fresh_call_after_historical_repeat() -> None:
    first = _call("same", "first")
    repeated = tuple(_call("same", f"repeat-{index}") for index in range(3))
    mixed_repeat = _call("same", "repeat-mixed")
    reset = _call("reset", "reset")
    fresh = _call("fresh", "fresh")
    model = _gateway(
        _completion("Read the baseline.", first),
        _completion("Read it again.", repeated[0]),
        _completion("Read it again.", repeated[1]),
        _completion("Get a different result.", reset),
        _completion("Read it again.", repeated[2]),
        _completion("Run the mixed batch.", mixed_repeat, fresh),
        _completion("Fresh evidence was collected."),
        _completion("Canonical final after the mixed batch."),
    )
    tools = StableEvidenceGateway({"same": "same", "reset": "reset", "fresh": "fresh"})

    result = _run(model, tools, max_parallel=2)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert tools.calls == [first, reset, fresh]


def test_convergence_observation_does_not_displace_real_user_tail() -> None:
    messages = [
        _message(MessageRole.USER, "Initial objective."),
        _message(MessageRole.ASSISTANT, "old evidence " * 180),
        _message(MessageRole.USER, "Second real user turn."),
        _message(MessageRole.ASSISTANT, "more old evidence " * 180),
        _message(MessageRole.USER, "Third real user turn."),
        _message(MessageRole.ASSISTANT, "latest evidence " * 180),
        _message(MessageRole.USER, "Fourth real user turn."),
    ]

    append_no_progress_observation(
        messages,
        metadata={"consecutive_no_progress_batches": 3},
        created_at=NOW,
    )
    compacted = compact_message_history(
        tuple(messages),
        user_goal="Initial objective.",
        max_tokens=250,
        created_at=NOW,
    )

    assert messages[-1].role is MessageRole.SYSTEM
    assert "Do not request or invoke another tool" in messages[-1].content
    assert compacted.compacted is True
    exact_user_turns = {
        message.content for message in compacted.messages if message.role is MessageRole.USER
    }
    assert {
        "Second real user turn.",
        "Third real user turn.",
        "Fourth real user turn.",
    } <= exact_user_turns


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
        _completion("Canonical final after the evidence chain."),
    )
    tools = StableEvidenceGateway(evidence_by_query)

    result = _run(model, tools)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["consecutive_no_progress_batches"] == 0
    assert result.run_result.tool_calls_used == 9
    assert len(tools.calls) == 9
    assert model.tool_requests.count(()) == 1


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
    policy: AllowAllPolicy | None = None,
):
    return HarnessLoop().run(
        HarnessTask(title="Convergence", user_input="Use the available evidence."),
        SingleAttemptOrchestrator(
            model,
            policy or AllowAllPolicy(),
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


def _message(role: MessageRole, content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=role,
        content=content,
        created_at=NOW,
    )
