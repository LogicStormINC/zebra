"""Wave 5 Phase 2 red/contract tests (ZNX-WAVE5-OUTER-ATTEMPTS-01).

Phase 2: generic evidence coverage verifier, bounded correction driven by the
frozen ``max_corrections_per_attempt`` policy, the exact retryable coverage
stop code, and the safe terminal coverage verdict. These tests MUST FAIL at
the starting HEAD ``4797af8`` (no harness correction budget, no exact code,
no terminal coverage verdict); Phase 2 production closes exactly these gaps.
"""

from datetime import UTC, datetime

import pytest
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
from agent_core.domain.attempt_policy import TaskAttemptPolicy
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import (
    ModelToolChoice,
    ModelToolDefinition,
)
from agent_core.domain.sessions import Session
from agent_core.domain.tools import ToolCallStatus
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
    HarnessLoop,
    HarnessStoppingPolicy,
    HarnessTask,
    StepClock,
)
from agent_core.harness.completion_blocking import append_missing_evidence_observation
from agent_core.harness.completion_evidence import (
    complete_without_tools,
    evaluate_completion_evidence,
    evaluate_context_completion_evidence,
)
from agent_core.harness.required_tool_request import (
    evidence_correction_request,
    selected_model_tools,
)

NOW = datetime(2026, 8, 15, 2, 0, tzinfo=UTC)

_FINANCIAL_REQUIREMENT = CompletionEvidenceRequirement(
    evidence_id="authoritative_financial",
    typed_evidence=("authoritative.financial.confirmed",),
)
_KNOWLEDGE_REQUIREMENT = CompletionEvidenceRequirement(
    evidence_id="confirmed_investor_knowledge",
    typed_evidence=("investor.knowledge.confirmed",),
)


def _financial_definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(_FINANCIAL_REQUIREMENT,)
        ),
    )


def _typed_tool_event(label: str) -> HarnessEventDraft:
    return HarnessEventDraft(
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "evidence.lookup",
            "tool_call_id": str(new_tool_call_id()),
            "status": ToolCallStatus.EXECUTED.value,
            "output": "trusted fact",
            "metadata": {"typed_evidence": [label]},
        },
    )


def _context(*, max_corrections_per_attempt: int) -> HarnessContext:
    task = HarnessTask(
        title="Coverage correction",
        user_input="Prove the evidence contract.",
        max_attempts=2,
        max_corrections_per_attempt=max_corrections_per_attempt,
        agent_definition=_financial_definition(),
        trusted_evidence_tools={
            "evidence.lookup": ("authoritative.financial.confirmed",)
        },
    )
    return HarnessContext(
        task=task,
        session=Session.create(title=task.title, created_at=NOW),
        attempt=HarnessAttempt(number=1, started_at=NOW),
    )


def _no_producer_context(*, max_corrections_per_attempt: int) -> HarnessContext:
    task = HarnessTask(
        title="Coverage correction",
        user_input="Prove the evidence contract.",
        max_attempts=2,
        max_corrections_per_attempt=max_corrections_per_attempt,
        agent_definition=_financial_definition(),
    )
    return HarnessContext(
        task=task,
        session=Session.create(title=task.title, created_at=NOW),
        attempt=HarnessAttempt(number=1, started_at=NOW),
    )


def _synthetic_completion(**kwargs):
    return HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="synthetic correction result",
        metadata=dict(kwargs["metadata"]),
    )


# P2-1: authoritative financial evidence and confirmed Investor Knowledge are
# independent generic requirement IDs/typed labels; one cannot satisfy the other.
def test_authoritative_financial_and_investor_knowledge_are_independent() -> None:
    definition = AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(_FINANCIAL_REQUIREMENT, _KNOWLEDGE_REQUIREMENT)
        ),
    )

    financial_only = evaluate_completion_evidence(
        definition, (_typed_tool_event("authoritative.financial.confirmed"),)
    )
    assert financial_only.satisfied is False
    assert financial_only.missing == ("confirmed_investor_knowledge",)

    knowledge_only = evaluate_completion_evidence(
        definition, (_typed_tool_event("investor.knowledge.confirmed"),)
    )
    assert knowledge_only.missing == ("authoritative_financial",)

    both = evaluate_completion_evidence(
        definition,
        (
            _typed_tool_event("authoritative.financial.confirmed"),
            _typed_tool_event("investor.knowledge.confirmed"),
        ),
    )
    assert both.satisfied is True
    assert both.missing == ()


# P2-2: only durable successful trusted typed tool results count. No final
# keywords, call counts, model self-report, failed/partial tool output or
# NoopVerifier can satisfy a typed requirement.
@pytest.mark.parametrize(
    ("label", "events"),
    (
        (
            "model self-report prose",
            (
                HarnessEventDraft(
                    event_type=EventType.MODEL_RESPONSE_RECEIVED,
                    actor=EventActor.HARNESS,
                    payload={
                        "assistant_message": "I read the authoritative financial evidence.",
                        "response_stage": "final",
                    },
                ),
            ),
        ),
        (
            "final keywords without typed label",
            (
                HarnessEventDraft(
                    event_type=EventType.TOOL_EXECUTION_COMPLETED,
                    actor=EventActor.TOOL,
                    payload={
                        "tool_call_id": str(new_tool_call_id()),
                        "status": ToolCallStatus.EXECUTED.value,
                        "output": "final answer with all required evidence",
                        "metadata": {},
                    },
                ),
            ),
        ),
        (
            "tool call count without labels",
            (
                HarnessEventDraft(
                    event_type=EventType.TOOL_EXECUTION_COMPLETED,
                    actor=EventActor.TOOL,
                    payload={
                        "tool_call_id": str(new_tool_call_id()),
                        "status": ToolCallStatus.EXECUTED.value,
                        "metadata": {"tool_tags": ["evidence"]},
                    },
                ),
            ),
        ),
        (
            "failed tool output",
            (
                HarnessEventDraft(
                    event_type=EventType.TOOL_EXECUTION_COMPLETED,
                    actor=EventActor.TOOL,
                    payload={
                        "tool_call_id": str(new_tool_call_id()),
                        "status": ToolCallStatus.FAILED.value,
                        "metadata": {
                            "typed_evidence": ["authoritative.financial.confirmed"]
                        },
                    },
                ),
            ),
        ),
        (
            "NoopVerifier outcome",
            (
                HarnessEventDraft(
                    event_type=EventType.TESTS_COMPLETED,
                    actor=EventActor.HARNESS,
                    payload={
                        "tool_call_id": "noop-verifier",
                        "tool_tags": ["validator"],
                        "passed": True,
                        "metadata": {"validator_outcome": "noop"},
                    },
                ),
            ),
        ),
    ),
)
def test_only_durable_successful_trusted_typed_results_count(
    label: str,
    events: tuple[HarnessEventDraft, ...],
) -> None:
    status = evaluate_completion_evidence(_financial_definition(), events)
    assert status.satisfied is False, label
    assert status.missing == ("authoritative_financial",), label


# P2-3: one correction only when the frozen max_corrections_per_attempt=1,
# then the exact stop code after that correction still misses coverage.
def test_one_bounded_correction_then_exact_after_correction_code() -> None:
    context = _context(max_corrections_per_attempt=1)
    corrections: list[dict[str, object]] = []

    def next_completion(_context, **kwargs):
        corrections.append(kwargs)
        return _synthetic_completion(**kwargs)

    complete_without_tools(
        context,
        messages=[],
        emitted_events=[],
        model_calls_used=0,
        tool_calls_executed=0,
        metadata={},
        assistant_message="candidate final",
        fingerprints=set(),
        request_next_completion=next_completion,
    )
    assert len(corrections) == 1
    assert corrections[0]["metadata"]["completion_evidence_observation_count"] == 1
    assert corrections[0]["metadata"]["required_evidence_tool_names"] == ("evidence.lookup",)

    second = complete_without_tools(
        context,
        messages=[],
        emitted_events=[],
        model_calls_used=1,
        tool_calls_executed=0,
        metadata=dict(corrections[0]["metadata"]),
        assistant_message="candidate final",
        fingerprints=set(),
        request_next_completion=next_completion,
    )
    assert second.outcome is HarnessAttemptOutcome.FAILED
    assert second.metadata["stop_reason"] == "completion_evidence_missing_after_correction"
    assert len(corrections) == 1


# P2-4: frozen max_corrections_per_attempt=0 performs no correction and keeps
# the legacy non-retryable code.
def test_max_zero_performs_no_correction_and_keeps_legacy_code() -> None:
    context = _context(max_corrections_per_attempt=0)
    corrections: list[dict[str, object]] = []

    result = complete_without_tools(
        context,
        messages=[],
        emitted_events=[],
        model_calls_used=0,
        tool_calls_executed=0,
        metadata={},
        assistant_message="candidate final",
        fingerprints=set(),
        request_next_completion=lambda **kwargs: corrections.append(kwargs)
        or _synthetic_completion(**kwargs),
    )
    assert corrections == []
    assert result.outcome is HarnessAttemptOutcome.FAILED
    assert result.metadata["stop_reason"] == "completion_evidence_missing"


# P1-3 core: typed evidence with no matching currently-advertised trusted
# producer must never dispatch a prompt-only correction.
def test_core_no_matching_producer_never_dispatches_correction() -> None:
    context = _no_producer_context(max_corrections_per_attempt=1)
    messages: list[SessionMessage] = []
    corrections: list[dict[str, object]] = []

    result = complete_without_tools(
        context,
        messages=messages,
        emitted_events=[],
        model_calls_used=0,
        tool_calls_executed=0,
        metadata={},
        assistant_message="candidate final",
        fingerprints=set(),
        request_next_completion=lambda _ctx, **kwargs: corrections.append(kwargs)
        or _synthetic_completion(**kwargs),
    )
    assert corrections == []
    assert messages == []
    assert result.outcome is HarnessAttemptOutcome.FAILED
    assert result.metadata["stop_reason"] == "completion_evidence_missing"
    assert result.metadata.get("completion_evidence_observation_count", 0) == 0


# P2-5: correction names only matching currently-advertised trusted producer
# tools with the required tool choice and the existing typed argument schema;
# no FinOS-specific tool name or manifest argument is invented.
def test_correction_uses_only_matching_advertised_producer_with_required_choice() -> None:
    messages: list[SessionMessage] = []
    producers = append_missing_evidence_observation(
        messages,
        missing=("authoritative_financial",),
        open_plan_steps=(),
        definition=_financial_definition(),
        trusted_evidence_tools={
            "evidence.lookup": ("authoritative.financial.confirmed",),
            "finos.resource.read": ("finos.manifest",),
        },
        created_at=NOW,
    )
    assert producers == ("evidence.lookup",)
    assert "finos.resource.read" not in producers

    request = evidence_correction_request({"required_evidence_tool_names": producers})
    assert request.tool_names == ("evidence.lookup",)
    assert request.invocation_policy is not None
    assert request.invocation_policy.tool_choice is ModelToolChoice.REQUIRED

    advertised = (
        ModelToolDefinition(
            name="evidence.lookup",
            description="Read trusted evidence.",
            parameters={
                "type": "object",
                "properties": {"ref": {"type": "string"}},
            },
        ),
    )
    selected = selected_model_tools(
        advertised,
        allow_tools=True,
        required_names=("evidence.lookup",),
    )
    assert [tool.name for tool in selected] == ["evidence.lookup"]
    assert selected[0].parameters == {
        "type": "object",
        "properties": {"ref": {"type": "string"}},
    }
    with pytest.raises(ValueError):
        selected_model_tools(
            advertised,
            allow_tools=True,
            required_names=("finos.resource.read",),
        )


# P2-6: the exact code, and only that coverage code, can be frozen as
# retryable; completion_evidence_missing stays absolutely non-retriable.
def test_only_exact_coverage_code_is_freezeable_as_retryable() -> None:
    policy = HarnessStoppingPolicy()
    after_correction = HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="evidence still missing after bounded correction",
        metadata={"stop_reason": "completion_evidence_missing_after_correction"},
    )
    assert (
        policy.should_retry(
            max_attempts=2,
            max_model_calls=None,
            max_tool_calls=None,
            attempts_used=1,
            model_calls_used=1,
            tool_calls_used=0,
            attempt_result=after_correction,
        )
        is True
    )
    frozen = TaskAttemptPolicy(
        max_attempts=2,
        max_corrections_per_attempt=1,
        retryable_stop_reasons=("completion_evidence_missing_after_correction",),
    )
    assert frozen.retryable_stop_reasons == ("completion_evidence_missing_after_correction",)
    with pytest.raises(ValueError):
        TaskAttemptPolicy(retryable_stop_reasons=("completion_evidence_missing",))


# P2-7: accepted evidence from durable successful typed results is available
# to Attempt 2; Attempt 1 prose is never accepted as fact.
def test_attempt_2_reuses_accepted_typed_evidence_not_attempt_1_prose() -> None:
    loop = HarnessLoop(
        clock=StepClock(
            current=NOW,
            step=datetime(2026, 8, 15, 2, 0, 1, tzinfo=UTC) - NOW,
        )
    )
    task = HarnessTask(
        title="Evidence carryover",
        user_input="Prove the evidence contract.",
        max_attempts=2,
        max_corrections_per_attempt=1,
        agent_definition=_financial_definition(),
        trusted_evidence_tools={
            "evidence.lookup": ("authoritative.financial.confirmed",)
        },
    )
    attempt_two_status: list[object] = []

    def runner(context: HarnessContext) -> HarnessAttemptResult:
        if context.attempt.number == 1:
            return HarnessAttemptResult(
                outcome=HarnessAttemptOutcome.FAILED,
                summary="evidence still missing after bounded correction",
                metadata={
                    "stop_reason": "completion_evidence_missing_after_correction",
                    "model_calls_used": 1,
                    "tool_calls_executed": 1,
                },
                emitted_events=(
                    _typed_tool_event("authoritative.financial.confirmed"),
                    HarnessEventDraft(
                        event_type=EventType.MODEL_RESPONSE_RECEIVED,
                        actor=EventActor.HARNESS,
                        payload={
                            "assistant_message": "Attempt 1 prose claims the evidence is read.",
                            "response_stage": "final",
                        },
                    ),
                ),
            )
        status = evaluate_context_completion_evidence(context, ())
        attempt_two_status.append(status)
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.COMPLETED,
            summary="accepted with the prior durable typed evidence",
            metadata={"model_calls_used": 1, "tool_calls_executed": 0},
        )

    result = loop.run(task, runner)

    assert result.run_result.final_outcome is HarnessAttemptOutcome.COMPLETED
    assert len(attempt_two_status) == 1
    assert attempt_two_status[0].satisfied is True
    assert attempt_two_status[0].missing == ()


# P2-8: the existing completion-evidence status metadata carries safe counts
# (no requirement IDs) so the terminal verdict can be derived without leaking
# private identifiers.
def test_completion_evidence_metadata_carries_safe_counts() -> None:
    from agent_core.harness.coverage_verdict import completion_status_metadata

    status = evaluate_completion_evidence(_financial_definition(), ())
    metadata = completion_status_metadata(status, {})
    assert metadata["completion_evidence_required_count"] == 1
    assert metadata["completion_evidence_satisfied_count"] == 0
    assert metadata["completion_evidence_missing_count"] == 1
    assert all(
        isinstance(metadata[key], int) and not isinstance(metadata[key], bool)
        for key in (
            "completion_evidence_required_count",
            "completion_evidence_satisfied_count",
            "completion_evidence_missing_count",
        )
    )
