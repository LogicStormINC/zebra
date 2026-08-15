from datetime import UTC, datetime

import pytest
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    AgentDefinitionContext,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessContext,
    HarnessLoop,
    HarnessModelStep,
    HarnessStopReason,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_core.harness.completion_evidence import evaluate_completion_evidence
from agent_core.harness.models import HarnessEventDraft

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
TOOLS = (
    ModelToolDefinition(
        name="evidence.lookup",
        description="Look up one typed evidence item.",
        parameters={"type": "object", "properties": {}},
    ),
    ModelToolDefinition(
        name="evidence.validate",
        description="Validate the current typed evidence.",
        parameters={"type": "object", "properties": {}},
    ),
    ModelToolDefinition(
        name="evidence.approve",
        description="Perform an approval-gated evidence action.",
        parameters={"type": "object", "properties": {}},
    ),
    ModelToolDefinition(
        name="agent.clarify",
        description="Ask the user for one clarification.",
        parameters={
            "type": "object",
            "properties": {"question": {"type": "string"}, "choices": {"type": "array"}},
        },
    ),
)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("agent_id", "agent-neutral\nUNTRUSTED_SYSTEM_TEXT"),
        ("version", "1.0.0\r\nUNTRUSTED_SYSTEM_TEXT"),
        ("agent_id", "agent-neutral\x00"),
    ),
)
def test_agent_definition_rejects_control_characters_in_identity(
    field: str,
    value: str,
) -> None:
    identity = {"agent_id": "agent-neutral", "version": "1.0.0"}
    identity[field] = value

    with pytest.raises(ValueError):
        AgentDefinition(**identity)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("system_prompt_ref", "system://trusted" + chr(10) + "UNTRUSTED"),
        ("skill_refs", ("skill://trusted" + chr(13),)),
        ("eval_suite_ref", "eval://suite" + chr(9)),
    ),
)
def test_agent_definition_rejects_control_characters_in_references(
    field: str,
    value: object,
) -> None:
    definition = {
        "agent_id": "agent-neutral",
        "version": "1.0.0",
        field: value,
    }

    with pytest.raises(ValueError):
        AgentDefinition(**definition)


def test_existing_identity_forms_render_as_one_system_context_line() -> None:
    definition = AgentDefinition(agent_id="agent-neutral", version="1.0.0")

    context = AgentDefinitionContext(
        agent_id=definition.agent_id,
        version=definition.version,
    )

    assert context.render() == "Agent definition context: agent-neutral@1.0.0"


def test_direct_context_rejects_render_injection() -> None:
    with pytest.raises(ValueError):
        AgentDefinitionContext(
            agent_id="agent-neutral" + chr(10) + "UNTRUSTED",
            version="1.0.0",
        )


class AllowAllPolicy:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed",
            policy_profile="test",
        )


class ApprovalPolicy(AllowAllPolicy):
    def evaluate_tool_call(self, tool_call: ToolCall) -> PolicyDecision:
        if tool_call.name == "evidence.approve":
            return PolicyDecision(
                decision=PolicyDecisionType.REQUIRE_APPROVAL,
                reason="approval required",
                policy_profile="test",
            )
        return super().evaluate_tool_call(tool_call)


class ScriptedGateway:
    def __init__(self, responses: tuple[ModelCompletion, ...]) -> None:
        self.responses = responses
        self.cursor = 0
        self.requests: list[tuple[SessionMessage, ...]] = []
        self.tool_requests: list[tuple[ModelToolDefinition, ...]] = []

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        self.requests.append(tuple(messages))
        self.tool_requests.append(tools)
        response = self.responses[self.cursor]
        self.cursor += 1
        return response


class EvidenceTools:
    def execute(self, tool_call: ToolCall) -> ToolResult:
        metadata: dict[str, object] = {}
        if tool_call.name == "evidence.lookup":
            metadata["typed_evidence"] = ["lookup.ready"]
        else:
            metadata["tool_tags"] = ["validator"]
            metadata["validator_outcome"] = "passed"
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=tool_call.name,
            metadata=metadata,
        )


class FailedValidatorTools:
    def execute(self, tool_call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.FAILED,
            output="validator execution failed",
            metadata={
                "tool_tags": ["validator"],
                "validator_result": {"passed": True},
            },
        )


def test_missing_typed_evidence_gets_one_bounded_observation() -> None:
    definition = _definition()
    gateway = ScriptedGateway(
        (
            _completion("The answer is ready."),
            _completion("I need to gather evidence.", _call("evidence.lookup")),
            _completion("Validate the evidence.", _call("evidence.validate")),
            _completion("The typed evidence is ready."),
        )
    )

    result = _run(gateway, EvidenceTools(), definition)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.run_result.model_calls_used == 4
    assert any(
        message.role is MessageRole.SYSTEM
        and "missing_completion_evidence" in message.content
        for message in gateway.requests[1]
    )


def test_required_evidence_can_arrive_in_any_tool_order() -> None:
    definition = _definition()
    first = _call("evidence.validate")
    second = _call("evidence.lookup")
    gateway = ScriptedGateway(
        (
            _completion("Validate first.", first),
            _completion("Look up second.", second),
            _completion("All required evidence passed."),
        )
    )

    result = _run(gateway, EvidenceTools(), definition, max_model_calls=3)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["completion_evidence_satisfied"] is True


def test_repeated_missing_evidence_fails_without_retry() -> None:
    definition = _definition()
    gateway = ScriptedGateway(
        (_completion("No typed evidence."), _completion("Still no typed evidence."))
    )

    result = _run(
        gateway,
        EvidenceTools(),
        definition,
        max_attempts=2,
        max_model_calls=2,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.attempt_result.metadata["stop_reason"] == "completion_evidence_missing"
    assert result.run_result.stop_reason is HarnessStopReason.COMPLETION_EVIDENCE_MISSING
    assert result.run_result.attempts_used == 1
    assert len(gateway.requests) == 2
    assert sum(
        "missing_completion_evidence" in message.content
        for request in gateway.requests
        for message in request
        if message.role is MessageRole.SYSTEM
    ) == 1


def test_failed_validator_result_cannot_satisfy_passed_evidence() -> None:
    definition = AgentDefinition(
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
    gateway = ScriptedGateway(
        (
            _completion("Validate the evidence.", _call("evidence.validate")),
            _completion("No trusted validation result."),
        )
    )

    result = _run(
        gateway,
        FailedValidatorTools(),
        definition,
        max_model_calls=2,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.attempt_result.metadata["completion_evidence_satisfied"] is False
    assert result.attempt_result.metadata["completion_evidence_missing"] == ["validation"]


def test_default_tool_loop_completion_is_gated_by_contract() -> None:
    definition = AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(
                CompletionEvidenceRequirement(
                    evidence_id="lookup",
                    typed_evidence=("lookup.ready",),
                ),
            )
        ),
    )
    gateway = ScriptedGateway(
        (
            _completion("Validate only.", _call("evidence.validate")),
            _completion("No lookup evidence."),
        )
    )

    result = _run(
        gateway,
        EvidenceTools(),
        definition,
        max_model_calls=2,
        synthesize_tool_results=None,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.attempt_result.metadata["stop_reason"] == "completion_evidence_missing"
    assert len(gateway.requests) == 2


def test_approved_continuation_retains_durable_completion_evidence() -> None:
    definition = _lookup_definition()
    pending = _call("evidence.approve")
    gateway = ScriptedGateway(
        (
            _completion("Look up the evidence.", _call("evidence.lookup")),
            _completion("Approval is required.", pending),
            _completion("The required evidence is ready."),
        )
    )
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        ApprovalPolicy(),
        EvidenceTools(),
        model_step=HarnessModelStep(available_tools=TOOLS),
        synthesize_tool_results=True,
    )
    task = HarnessTask(
        title="Approval evidence continuity",
        user_input="Collect the required typed evidence.",
        max_model_calls=3,
        agent_definition=definition,
    )
    waiting = HarnessLoop().run(task, orchestrator.run, created_at=NOW)
    approval = next(
        event
        for event in waiting.events
        if event.event_type.value == "approval_requested"
    )
    conversation = tuple(
        SessionMessage.model_validate(message) for message in approval.payload["conversation"]
    )

    completed = orchestrator.continue_approved_tool_call(
        HarnessContext(
            task=task,
            session=waiting.session,
            attempt=HarnessAttempt(number=1, started_at=NOW),
            completion_evidence_events=waiting.events,
        ),
        initial_completion=_completion("Approval is required.", pending),
        tool_call=pending,
        conversation=conversation,
        model_calls_used=2,
        tool_calls_executed=1,
    )

    assert completed.outcome is HarnessAttemptOutcome.COMPLETED


def test_clarification_continuation_retains_durable_completion_evidence() -> None:
    definition = _lookup_definition()
    gateway = ScriptedGateway(
        (
            _completion("Look up the evidence.", _call("evidence.lookup")),
            _completion(
                "Clarification is required.",
                ToolCall(
                    tool_call_id=new_tool_call_id(),
                    name="agent.clarify",
                    arguments={"question": "Proceed?", "choices": ["yes", "no"]},
                    created_at=NOW,
                ),
            ),
            _completion("The required evidence is ready."),
        )
    )
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicy(),
        EvidenceTools(),
        model_step=HarnessModelStep(available_tools=TOOLS),
        synthesize_tool_results=True,
    )
    task = HarnessTask(
        title="Clarification evidence continuity",
        user_input="Collect the required typed evidence.",
        max_model_calls=3,
        agent_definition=definition,
    )
    waiting = HarnessLoop().run(task, orchestrator.run, created_at=NOW)
    clarification = next(
        event
        for event in waiting.events
        if event.event_type.value == "clarification_requested"
    )
    conversation = tuple(
        SessionMessage.model_validate(message)
        for message in clarification.payload["conversation"]
    )
    clarify_call = next(
        call
        for message in conversation
        for call in message.tool_calls
        if call.name == "agent.clarify"
    )

    completed = orchestrator.continue_clarification(
        HarnessContext(
            task=task,
            session=waiting.session,
            attempt=HarnessAttempt(number=1, started_at=NOW),
            completion_evidence_events=waiting.events,
        ),
        tool_call=clarify_call,
        response="yes",
        conversation=conversation,
        model_calls_used=2,
        tool_calls_executed=1,
        assistant_message="Clarification is required.",
    )

    assert completed.outcome is HarnessAttemptOutcome.COMPLETED


def test_tampered_persisted_validator_evidence_fails_closed() -> None:
    definition = AgentDefinition(
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
    tool_call_id = str(new_tool_call_id())
    status = evaluate_completion_evidence(
        definition,
        (
            HarnessEventDraft(
                event_type=EventType.TOOL_EXECUTION_COMPLETED,
                actor=EventActor.TOOL,
                payload={
                    "tool_call_id": tool_call_id,
                    "status": ToolCallStatus.FAILED.value,
                    "metadata": {"tool_tags": ["validator"]},
                },
            ),
            HarnessEventDraft(
                event_type=EventType.TESTS_COMPLETED,
                actor=EventActor.HARNESS,
                payload={
                    "tool_call_id": tool_call_id,
                    "tool_tags": ["validator"],
                    "passed": True,
                    "metadata": {"validator_outcome": "passed"},
                },
            ),
        ),
    )

    assert status.satisfied is False
    assert status.missing == ("validation",)


def test_approved_continuation_runs_model_capability_preflight() -> None:
    gateway = ScriptedGateway((_completion("must not run"),))
    task = HarnessTask(
        title="Approval capability preflight",
        user_input="Use the required model capability.",
        agent_definition=AgentDefinition(
            agent_id="agent-neutral",
            version="1.0.0",
            required_model_capabilities=("image",),
        ),
        model_capabilities=("text",),
    )
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicy(),
        EvidenceTools(),
        model_step=HarnessModelStep(available_tools=TOOLS),
    )
    pending = _call("evidence.lookup")

    result = orchestrator.continue_approved_tool_call(
        HarnessContext(task=task, session=_session(), attempt=HarnessAttempt(1, NOW)),
        initial_completion=_completion("Use the approved call.", pending),
        tool_call=pending,
    )

    assert result.outcome is HarnessAttemptOutcome.FAILED
    assert result.metadata["stop_reason"] == "agent_definition_model_capability_missing"
    assert gateway.requests == []


def test_clarification_continuation_runs_model_capability_preflight() -> None:
    gateway = ScriptedGateway((_completion("must not run"),))
    task = HarnessTask(
        title="Clarification capability preflight",
        user_input="Use the required model capability.",
        agent_definition=AgentDefinition(
            agent_id="agent-neutral",
            version="1.0.0",
            required_model_capabilities=("image",),
        ),
        model_capabilities=("text",),
    )
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicy(),
        EvidenceTools(),
        model_step=HarnessModelStep(available_tools=TOOLS),
    )
    clarify_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.clarify",
        arguments={"question": "Proceed?", "choices": ["yes", "no"]},
        created_at=NOW,
    )
    conversation = (
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="Clarification is required.",
            created_at=NOW,
            tool_calls=(clarify_call,),
        ),
    )

    result = orchestrator.continue_clarification(
        HarnessContext(task=task, session=_session(), attempt=HarnessAttempt(1, NOW)),
        tool_call=clarify_call,
        response="yes",
        conversation=conversation,
        model_calls_used=1,
        tool_calls_executed=0,
        assistant_message="Clarification is required.",
    )

    assert result.outcome is HarnessAttemptOutcome.FAILED
    assert result.metadata["stop_reason"] == "agent_definition_model_capability_missing"
    assert gateway.requests == []


def _lookup_definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(
                CompletionEvidenceRequirement(
                    evidence_id="lookup",
                    typed_evidence=("lookup.ready",),
                ),
            )
        ),
    )


def _session():
    from agent_core.domain.sessions import Session

    return Session.create(title="Continuation preflight", created_at=NOW)


def test_no_definition_keeps_legacy_no_tool_completion() -> None:
    gateway = ScriptedGateway((_completion("Direct answer."),))

    result = _run(gateway, EvidenceTools(), None)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.run_result.model_calls_used == 1


def test_resolved_definition_context_is_a_system_message() -> None:
    messages = HarnessModelStep().build_initial_messages(
        HarnessTask(
            title="System context",
            user_input="Use the configured context.",
            agent_definition=AgentDefinition(agent_id="agent-neutral", version="1.0.0"),
            agent_context=AgentDefinitionContext(
                agent_id="agent-neutral",
                version="1.0.0",
                system_prompt="Trusted system instruction.",
            ),
        ),
        created_at=NOW,
    )

    assert messages[0].role is MessageRole.SYSTEM
    assert "Trusted system instruction." in messages[0].content


def test_missing_required_model_capability_fails_closed() -> None:
    gateway = ScriptedGateway((_completion("must not run"),))
    definition = AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        required_model_capabilities=("image",),
    )

    result = _run(gateway, EvidenceTools(), definition)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.attempt_result.metadata["stop_reason"] == (
        "agent_definition_model_capability_missing"
    )
    assert gateway.requests == []


def _definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="agent-neutral",
        version="2026.08.02",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(
                CompletionEvidenceRequirement(
                    evidence_id="lookup",
                    typed_evidence=("lookup.ready",),
                ),
                CompletionEvidenceRequirement(
                    evidence_id="validation",
                    validator_outcome="passed",
                ),
            )
        ),
    )


def _run(
    gateway: ScriptedGateway,
    tools: EvidenceTools,
    definition: AgentDefinition | None,
    *,
    max_attempts: int = 1,
    max_model_calls: int | None = None,
    synthesize_tool_results: bool | None = True,
):
    orchestrator_kwargs: dict[str, object] = {}
    if synthesize_tool_results is not None:
        orchestrator_kwargs["synthesize_tool_results"] = synthesize_tool_results
    return HarnessLoop().run(
        HarnessTask(
            title="Neutral evidence task",
            user_input="Collect the required typed evidence.",
            max_attempts=max_attempts,
            max_model_calls=max_model_calls,
            agent_definition=definition,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            **orchestrator_kwargs,
        ).run,
        created_at=NOW,
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


def _call(name: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        created_at=NOW,
    )
