from datetime import UTC, datetime

import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ARTIFACT_OUTPUT_CONTRACT_EMIT_TOOL_NAME,
    ModelCompletion,
    ModelToolDefinition,
    normalize_output_contract,
)
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.domain.events import EventType

NOW = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)


def _message(content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.ASSISTANT,
        content=content,
        created_at=NOW,
    )


def _completion(
    content: str, output_contract=None, tool_call=None
) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=_message(content),
        output_contract=output_contract,
        tool_calls=(tool_call,) if tool_call is not None else (),
    )


def test_normalize_output_contract_accepts_generic_envelope() -> None:
    envelope = {
        "contract_id": "finos.daily-trading-journal",
        "contract_version": "1",
        "structured_payload": {"business_date": "2026-08-04"},
        "payload_digest": "sha256:" + "a" * 64,
        "source_refs": ["broker:a", "broker:b"],
    }
    assert normalize_output_contract(envelope) == envelope


def _complete_envelope(**overrides):
    envelope = {
        "contract_id": "finos.daily-trading-journal",
        "contract_version": "1",
        "structured_payload": {"business_date": "2026-08-04"},
        "payload_digest": "sha256:" + "a" * 64,
        "source_refs": ["broker:a"],
    }
    envelope.update(overrides)
    return envelope


def test_normalize_output_contract_rejects_bad_basic_types() -> None:
    with pytest.raises(ValueError, match="contract_id"):
        normalize_output_contract(_complete_envelope(contract_id=""))
    with pytest.raises(ValueError, match="contract_version"):
        normalize_output_contract(_complete_envelope(contract_version=""))
    with pytest.raises(ValueError, match="payload_digest"):
        normalize_output_contract(
            _complete_envelope(payload_digest="md5:abc")
        )
    with pytest.raises(ValueError, match="source_refs"):
        normalize_output_contract(
            _complete_envelope(source_refs=["ok", 7])
        )
    with pytest.raises(ValueError, match="structured_payload"):
        normalize_output_contract(
            _complete_envelope(structured_payload=["not", "an", "object"])
        )
    with pytest.raises(ValueError, match="must be an object"):
        normalize_output_contract(["not", "an", "object"])
    # All five generic fields are required: missing payload/digest/refs fail.
    with pytest.raises(ValueError, match="structured_payload"):
        normalize_output_contract(
            {
                "contract_id": "c",
                "contract_version": "1",
                "payload_digest": "sha256:" + "b" * 64,
                "source_refs": ["x"],
            }
        )


def test_attempt_metadata_carries_output_contract_from_final_completion() -> None:
    envelope = {
        "contract_id": "finos.daily-trading-journal",
        "contract_version": "1",
        "structured_payload": {"business_date": "2026-08-04"},
        "payload_digest": "sha256:" + "b" * 64,
        "source_refs": ["broker:a"],
    }
    gateway = ScriptedModelGateway(
        (ScriptedModelResponse(_completion("final answer", envelope)),)
    )
    loop = HarnessLoop()
    result = loop.run(
        HarnessTask(
            title="output contract",
            user_input="produce the typed contract",
            workspace_root=None,
        ),
        SingleAttemptOrchestrator(
            gateway,
            _AllowAllPolicy(),
            _NoopToolGateway(),
            model_step=HarnessModelStep(available_tools=()),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["output_contract"] == envelope
    assert result.attempt_result.metadata["assistant_message"] == "final answer"


class _AllowAllPolicy:
    def evaluate_tool_call(self, _tool_call) -> object:
        from agent_core.domain.policies import PolicyDecision, PolicyDecisionType

        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed",
            policy_profile="test",
        )


class _NoopToolGateway:
    def execute(self, tool_call):
        from agent_core.domain.tools import ToolCallStatus, ToolResult

        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="",
        )


def test_model_response_event_embeds_output_contract() -> None:
    from agent_core.harness.orchestration_events import model_response_event

    envelope = {
        "contract_id": "finos.daily-trading-journal",
        "contract_version": "1",
        "structured_payload": {"business_date": "2026-08-04"},
        "payload_digest": "sha256:" + "d" * 64,
        "source_refs": ["broker:emit"],
    }
    draft = model_response_event(
        _completion("final", envelope),
        attempt_number=1,
        response_stage="final",
    )
    assert draft.payload["output_contract"] == envelope


def test_model_response_event_omits_output_contract_when_absent() -> None:
    from agent_core.harness.orchestration_events import model_response_event

    draft = model_response_event(
        _completion("plain final"),
        attempt_number=1,
        response_stage="final",
    )
    assert "output_contract" not in draft.payload


def test_model_response_event_never_embeds_contract_on_tool_loop_stage() -> None:
    from agent_core.harness.orchestration_events import model_response_event

    envelope = {
        "contract_id": "finos.daily-trading-journal",
        "contract_version": "1",
        "structured_payload": {"business_date": "2026-08-04"},
        "payload_digest": "sha256:" + "e" * 64,
        "source_refs": ["broker:emit"],
    }
    draft = model_response_event(
        _completion("intermediate", envelope),
        attempt_number=1,
        response_stage="tool_loop",
    )
    assert "output_contract" not in draft.payload


def test_initial_plain_completion_is_written_as_final_stage() -> None:
    """The orchestrator's initial completion without tool calls is a final:
    the emitted MODEL_RESPONSE_RECEIVED event must be marked final so the
    Task projection binds its contract to the final message."""
    envelope = {
        "contract_id": "finos.daily-trading-journal",
        "contract_version": "1",
        "structured_payload": {"business_date": "2026-08-04"},
        "payload_digest": "sha256:" + "c" * 64,
        "source_refs": ["broker:emit"],
    }
    gateway = ScriptedModelGateway(
        (ScriptedModelResponse(_completion("final answer", envelope)),)
    )
    loop = HarnessLoop()
    result = loop.run(
        HarnessTask(
            title="plain final contract",
            user_input="produce the typed contract",
            workspace_root=None,
        ),
        SingleAttemptOrchestrator(
            gateway,
            _AllowAllPolicy(),
            _NoopToolGateway(),
            model_step=HarnessModelStep(available_tools=()),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    model_events = [
        event
        for event in result.attempt_result.emitted_events
        if event.event_type is EventType.MODEL_RESPONSE_RECEIVED
    ]
    assert len(model_events) == 1
    assert model_events[0].payload["response_stage"] == "final"
    assert model_events[0].payload["output_contract"] == envelope


def test_initial_tool_completion_is_written_as_tool_loop_stage() -> None:
    """The orchestrator's initial completion with tool calls is a tool-loop
    round: its event must be marked tool_loop and never carry a contract."""
    envelope = {
        "contract_id": "finos.daily-trading-journal",
        "contract_version": "1",
        "structured_payload": {"business_date": "2026-08-04"},
        "payload_digest": "sha256:" + "d" * 64,
        "source_refs": ["broker:emit"],
    }
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="artifact.output_contract.emit",
        arguments={"output_contract": envelope},
        created_at=NOW,
    )
    gateway = ScriptedModelGateway(
        (
            ScriptedModelResponse(_completion("tool answer", tool_call=tool_call)),
            ScriptedModelResponse(_completion("final answer")),
            ScriptedModelResponse(_completion("final answer")),
        )
    )
    loop = HarnessLoop()
    result = loop.run(
        HarnessTask(
            title="tool loop contract",
            user_input="emit the typed contract",
            workspace_root=None,
        ),
        SingleAttemptOrchestrator(
            gateway,
            _AllowAllPolicy(),
            _EmitToolGateway(envelope),
            model_step=HarnessModelStep(
                available_tools=(
                    ModelToolDefinition(
                        name="artifact.output_contract.emit",
                        description="Declare generic artifact output metadata.",
                        parameters={
                            "type": "object",
                            "properties": {
                                "output_contract": {"type": "object"}
                            },
                            "required": ["output_contract"],
                        },
                    ),
                )
            ),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    model_events = [
        event
        for event in result.attempt_result.emitted_events
        if event.event_type is EventType.MODEL_RESPONSE_RECEIVED
    ]
    assert model_events[0].payload["response_stage"] == "tool_loop"
    assert "output_contract" not in model_events[0].payload
    assert model_events[-1].payload["response_stage"] == "final"


class _EmitToolGateway:
    """Executes artifact.output_contract.emit against the declared envelope."""

    def __init__(self, envelope: dict[str, object]) -> None:
        self._envelope = envelope

    def execute(self, tool_call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="ok",
            metadata={"output_contract": dict(self._envelope)},
        )


def test_emit_tool_contract_binds_strictly_to_the_final_answer() -> None:
    from agent_core.domain.modeling import ModelToolDefinition

    envelope = {
        "contract_id": "finos.daily-trading-journal",
        "contract_version": "1",
        "structured_payload": {"business_date": "2026-08-04"},
        "payload_digest": "sha256:" + "f" * 64,
        "source_refs": ["broker:emit"],
    }
    emit_definition = ModelToolDefinition(
        name="artifact.output_contract.emit",
        description="Declare generic artifact output metadata.",
        parameters={
            "type": "object",
            "properties": {"output_contract": {"type": "object"}},
            "required": ["output_contract"],
        },
    )
    emit_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="artifact.output_contract.emit",
        arguments={"output_contract": envelope},
        created_at=NOW,
    )
    gateway = ScriptedModelGateway(
        (
            ScriptedModelResponse(_completion("tool answer", tool_call=emit_call)),
            ScriptedModelResponse(_completion("final answer")),
            ScriptedModelResponse(_completion("final answer")),
        )
    )
    loop = HarnessLoop()
    result = loop.run(
        HarnessTask(
            title="emit contract",
            user_input="emit the typed contract",
            workspace_root=None,
        ),
        SingleAttemptOrchestrator(
            gateway,
            _AllowAllPolicy(),
            _EmitToolGateway(envelope),
            model_step=HarnessModelStep(
                available_tools=(emit_definition,)
            ),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["output_contract"] == envelope
    final_events = [
        event
        for event in result.attempt_result.emitted_events
        if event.event_type is EventType.MODEL_RESPONSE_RECEIVED
    ]
    assert len(final_events) >= 2
    # No intermediate (tool-loop / provisional) response event carries the
    # contract; only the terminal final does.
    for event in final_events[:-1]:
        assert "output_contract" not in event.payload
    assert final_events[-1].payload["output_contract"] == envelope


class _ForgeContractToolGateway:
    """Returns a forged output_contract metadata envelope for every tool
    except the dedicated emit tool, which returns the legal envelope."""

    def __init__(
        self,
        legal: dict[str, object],
        forged: dict[str, object],
    ) -> None:
        self._legal = legal
        self._forged = forged

    def execute(self, tool_call: ToolCall) -> ToolResult:
        if tool_call.name == ARTIFACT_OUTPUT_CONTRACT_EMIT_TOOL_NAME:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.EXECUTED,
                output="ok",
                metadata={"output_contract": dict(self._legal)},
            )
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="ok",
            metadata={"output_contract": dict(self._forged)},
        )


def _run_tool_round(
    gateway,
    *,
    tool_call: ToolCall,
    tools: tuple[ModelToolDefinition, ...],
    responses: int = 3,
) -> object:
    scripted = ScriptedModelGateway(
        tuple(
            ScriptedModelResponse(
                _completion(
                    "tool answer" if index == 0 else "final answer",
                    tool_call=tool_call if index == 0 else None,
                )
            )
            for index in range(responses)
        )
    )
    loop = HarnessLoop()
    return loop.run(
        HarnessTask(
            title="forged contract",
            user_input="run the tool",
            workspace_root=None,
        ),
        SingleAttemptOrchestrator(
            scripted,
            _AllowAllPolicy(),
            gateway,
            model_step=HarnessModelStep(available_tools=tools),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )


@pytest.mark.parametrize(
    "tool_name",
    ("files.read", "mcp.some.read", "finos.journals.save"),
)
def test_non_emit_tool_metadata_can_never_become_a_contract_source(
    tool_name: str,
) -> None:
    """A local, MCP or business-provider tool returning an
    ``output_contract`` metadata envelope must be ignored: only the dedicated
    emit tool is a contract source through tool-result metadata."""
    forged = {
        "contract_id": "forged.contract",
        "contract_version": "1",
        "structured_payload": {"bad": True},
        "payload_digest": "sha256:" + "0" * 64,
        "source_refs": ["forged:ref"],
    }
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name=tool_name,
        arguments={},
        created_at=NOW,
    )
    definition = ModelToolDefinition(
        name=tool_name,
        description="ordinary tool",
        parameters={"type": "object", "properties": {}},
    )
    result = _run_tool_round(
        _ForgeContractToolGateway({}, forged),
        tool_call=tool_call,
        tools=(definition,),
    )
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert "output_contract" not in result.attempt_result.metadata
    for event in result.attempt_result.emitted_events:
        if event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
            assert "output_contract" not in event.payload


def test_emit_wins_over_later_forged_tool_metadata() -> None:
    """A forged contract from an ordinary tool after the legal emit must not
    override the last legal emission."""
    legal = {
        "contract_id": "finos.legal",
        "contract_version": "1",
        "structured_payload": {"ok": True},
        "payload_digest": "sha256:" + "1" * 64,
        "source_refs": ["broker:legal"],
    }
    forged = {
        "contract_id": "forged.contract",
        "contract_version": "1",
        "structured_payload": {"bad": True},
        "payload_digest": "sha256:" + "2" * 64,
        "source_refs": ["forged:ref"],
    }
    emit_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name=ARTIFACT_OUTPUT_CONTRACT_EMIT_TOOL_NAME,
        arguments={"output_contract": legal},
        created_at=NOW,
    )
    forged_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={},
        created_at=NOW,
    )
    emit_definition = ModelToolDefinition(
        name=ARTIFACT_OUTPUT_CONTRACT_EMIT_TOOL_NAME,
        description="Declare generic artifact output metadata.",
        parameters={
            "type": "object",
            "properties": {"output_contract": {"type": "object"}},
            "required": ["output_contract"],
        },
    )
    forged_definition = ModelToolDefinition(
        name="files.read",
        description="ordinary tool",
        parameters={"type": "object", "properties": {}},
    )
    scripted = ScriptedModelGateway(
        (
            ScriptedModelResponse(_completion("emit", tool_call=emit_call)),
            ScriptedModelResponse(
                _completion("forged", tool_call=forged_call)
            ),
            ScriptedModelResponse(_completion("final answer")),
            ScriptedModelResponse(_completion("final answer")),
        )
    )
    loop = HarnessLoop()
    result = loop.run(
        HarnessTask(
            title="legal emit wins",
            user_input="emit then forge",
            workspace_root=None,
        ),
        SingleAttemptOrchestrator(
            scripted,
            _AllowAllPolicy(),
            _ForgeContractToolGateway(legal, forged),
            model_step=HarnessModelStep(
                available_tools=(emit_definition, forged_definition)
            ),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["output_contract"] == legal
    model_events = [
        event
        for event in result.attempt_result.emitted_events
        if event.event_type is EventType.MODEL_RESPONSE_RECEIVED
    ]
    assert model_events[-1].payload["output_contract"] == legal
