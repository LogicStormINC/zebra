"""Wave 5 Phase 2 red/contract tests (ZNX-WAVE5-OUTER-ATTEMPTS-01).

Phase 2: generic evidence coverage verifier, bounded correction driven by the
frozen ``max_corrections_per_attempt`` policy, the exact retryable coverage
stop code, and the safe terminal coverage verdict. These tests MUST FAIL at
the starting HEAD ``4797af8`` (no harness correction budget, no exact code,
no terminal coverage verdict); Phase 2 production closes exactly these gaps.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
from agent_core.domain.attempt_policy import TaskAttemptPolicy
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelToolChoice,
    ModelToolDefinition,
    ModelUsage,
)
from agent_core.domain.sessions import Session
from agent_core.domain.tool_profiles import ToolProfile
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
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from worker_execution_support import _build_execution_service, _created_at
from zebra_agent_worker import SessionRecoveryService

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


class _AlwaysAssistantGateway:
    provider = "test"
    model_name = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, *, tools=(), media_inputs=()):
        del tools, media_inputs
        self.calls += 1
        return ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content="No typed evidence is available.",
                created_at=_created_at(),
            ),
            call_metadata=ModelCallMetadata(
                provider="test",
                model_name="test-model",
                usage=ModelUsage(total_tokens=1),
            ),
        )


def _seed_coverage_session(database_path: Path, workspace_root: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Queued coverage task",
            user_input="Complete the analysis.",
            workspace_root=workspace_root.resolve(),
            tool_profile=ToolProfile.CODING,
            max_attempts=2,
            max_corrections_per_attempt=1,
            agent_definition=_financial_definition(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SessionRecoveryService(
        event_store,
        SQLiteProjectionStore(database_path),
        SQLiteWorkspaceProjectionStore(database_path),
    ).recover_session(bootstrap.session.session_id)
    return bootstrap


# P2-9: the hosted worker runs the bounded correction once per Attempt, starts
# Attempt 2 with the exact coverage code, and terminals with a safe coverage
# verdict after retry exhaustion.
def test_hosted_worker_exhausts_coverage_retry_with_safe_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "wave5-p2-9.db"
    bootstrap = _seed_coverage_session(database_path, tmp_path)
    session_id = bootstrap.session.session_id
    gateway = _AlwaysAssistantGateway()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="wave5-p2-9",
        executed_at=_created_at(),
    )

    events = SQLiteEventStore(database_path).list_for_session(session_id)
    starts = [
        event
        for event in events
        if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    assert [event.payload["attempt_sequence"] for event in starts] == [1, 2]
    outcomes = [
        event
        for event in events
        if event.event_type is EventType.ATTEMPT_OUTCOME_RECORDED
    ]
    assert [event.payload["retry_scheduled"] for event in outcomes] == [True, False]
    failed = next(event for event in events if event.event_type is EventType.SESSION_FAILED)
    assert failed.payload["attempt_number"] == 2
    assert failed.payload["metadata"]["stop_reason"] == (
        "completion_evidence_missing_after_correction"
    )
    assert failed.payload["retryable"] is False
    verdict = failed.payload["coverage_verdict"]
    assert verdict["status"] == "missing"
    assert verdict["required_count"] == 1
    assert verdict["satisfied_count"] == 0
    assert verdict["missing_count"] == 1
    assert "authoritative_financial" not in verdict["message"]
    assert gateway.calls == 4  # initial + one correction per Attempt, two Attempts


# P2-10: the public projection carries only the safe coverage verdict; private
# requirement IDs, evidence refs, digests and diagnostics never become public.
def test_public_projection_exposes_only_safe_coverage_verdict(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_core.application.public_conversation import project_public_conversation
    from agent_storage import SQLiteAgentTaskStore
    from zebra_agent_api.task_final_identity import final_message_identity

    database_path = tmp_path / "wave5-p2-10.db"
    bootstrap = _seed_coverage_session(database_path, tmp_path)
    session_id = bootstrap.session.session_id
    gateway = _AlwaysAssistantGateway()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )
    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="wave5-p2-10",
        executed_at=_created_at(),
    )
    task_store = SQLiteAgentTaskStore(database_path)
    task = task_store.ensure_for_session(session_id)
    task_events = task_store.read_events(task.task_id, -1)

    projection = project_public_conversation(task.task_id, task_events)
    final_items = [item for item in projection.items if item.role == "final_response"]
    assert final_items == []
    failure_items = [item for item in projection.items if item.role == "failure"]
    assert len(failure_items) == 1
    assert failure_items[0].data["retryable"] is False
    verdict = failure_items[0].data["coverage_verdict"]
    assert set(verdict) == {
        "status",
        "required_count",
        "satisfied_count",
        "missing_count",
        "message",
    }
    assert final_message_identity(database_path, str(task.task_id)) is None
    leaked = {
        key
        for item in projection.items
        for key in (*item.data, item.content)
        if "authoritative_financial" in str(key)
        or "sha256:" in str(key)
        or "completion_evidence_missing" in str(key)
    }
    assert leaked == set()
