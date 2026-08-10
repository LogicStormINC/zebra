from datetime import UTC, datetime

import pytest
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.sessions import Session
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.completion_evidence import evaluate_completion_evidence
from agent_core.harness.hooks import NoopVerifier
from agent_core.harness.models import HarnessAttempt, HarnessContext, HarnessEventDraft, HarnessTask
from agent_core.harness.tool_execution import record_tool_result

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def test_conflicting_validator_fields_fail_closed_on_recorded_success() -> None:
    definition = _validator_definition()
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="evidence.validate",
        created_at=NOW,
    )
    events: list[HarnessEventDraft] = []
    record_tool_result(
        _context(definition),
        tool_call,
        ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="validation completed",
            metadata={
                "tool_tags": ["validator"],
                "validator_result": {"passed": False},
                "validator_outcome": "passed",
            },
        ),
        verifier=NoopVerifier(),
        emitted_events=events,
        tool_tags=("validator",),
    )
    tests_event = next(event for event in events if event.event_type is EventType.TESTS_COMPLETED)
    assert tests_event.payload["passed"] is False
    assert "validator_outcome" not in tests_event.payload["metadata"]

    status = evaluate_completion_evidence(definition, events)

    assert status.satisfied is False
    assert status.missing == ("validation",)


@pytest.mark.parametrize(
    ("event_type", "status", "metadata", "satisfied"),
    (
        (
            EventType.TOOL_EXECUTION_COMPLETED,
            ToolCallStatus.EXECUTED.value,
            {"typed_evidence": ["authoritative_typed_read"]},
            True,
        ),
        (
            EventType.TOOL_EXECUTION_COMPLETED,
            ToolCallStatus.EXECUTED.value,
            {"tool_tags": ["effect:read_only"]},
            False,
        ),
        (
            EventType.TOOL_EXECUTION_FAILED,
            ToolCallStatus.FAILED.value,
            {"typed_evidence": ["authoritative_typed_read"]},
            False,
        ),
    ),
)
def test_authoritative_typed_read_requires_successful_metadata_coverage(
    event_type: EventType,
    status: str,
    metadata: dict[str, object],
    satisfied: bool,
) -> None:
    definition = AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(
                CompletionEvidenceRequirement(
                    evidence_id="authoritative_financial_evidence",
                    typed_evidence=("authoritative_typed_read",),
                ),
            )
        ),
    )
    evidence = evaluate_completion_evidence(
        definition,
        (
            HarnessEventDraft(
                event_type=event_type,
                actor=EventActor.TOOL,
                payload={
                    "tool_call_id": str(new_tool_call_id()),
                    "status": status,
                    "metadata": metadata,
                },
            ),
        ),
    )

    assert evidence.satisfied is satisfied
    assert evidence.missing == (() if satisfied else ("authoritative_financial_evidence",))


@pytest.mark.parametrize(
    ("event_type", "actor", "status"),
    (
        (EventType.TOOL_EXECUTION_FAILED, EventActor.TOOL, ToolCallStatus.FAILED.value),
        (EventType.TOOL_EXECUTION_COMPLETED, EventActor.TOOL, "rejected"),
        (EventType.TOOL_EXECUTION_COMPLETED, EventActor.TOOL, "cancelled"),
        (EventType.TOOL_EXECUTION_COMPLETED, EventActor.HARNESS, ToolCallStatus.EXECUTED.value),
        (EventType.TESTS_COMPLETED, EventActor.TOOL, ToolCallStatus.EXECUTED.value),
    ),
)
def test_noncanonical_validator_events_never_satisfy_passed_evidence(
    event_type: EventType,
    actor: EventActor,
    status: str,
) -> None:
    definition = _validator_definition()
    event = HarnessEventDraft(
        event_type=event_type,
        actor=actor,
        payload={
            "tool_call_id": str(new_tool_call_id()),
            "status": status,
            "tool_tags": ["validator"],
            "metadata": {
                "validator_result": {"passed": True},
                "validator_outcome": "passed",
            },
        },
    )

    status = evaluate_completion_evidence(definition, (event,))

    assert status.satisfied is False
    assert status.missing == ("validation",)


def _validator_definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(
                CompletionEvidenceRequirement(
                    evidence_id="validation",
                    validator_outcome="passed",
                ),
            )
        ),
    )


def _context(definition: AgentDefinition) -> HarnessContext:
    return HarnessContext(
        task=HarnessTask(
            title="Validator evidence trust",
            user_input="Collect typed evidence.",
            agent_definition=definition,
        ),
        session=Session.create(title="Validator evidence trust", created_at=NOW),
        attempt=HarnessAttempt(number=1, started_at=NOW),
    )
