from datetime import UTC, datetime

import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    normalize_output_contract,
)
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)

NOW = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)


def _message(content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.ASSISTANT,
        content=content,
        created_at=NOW,
    )


def _completion(content: str, output_contract=None) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=_message(content),
        output_contract=output_contract,
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


def test_normalize_output_contract_rejects_bad_basic_types() -> None:
    with pytest.raises(ValueError, match="contract_id"):
        normalize_output_contract({"contract_version": "1"})
    with pytest.raises(ValueError, match="payload_digest"):
        normalize_output_contract(
            {
                "contract_id": "c",
                "contract_version": "1",
                "payload_digest": "md5:abc",
            }
        )
    with pytest.raises(ValueError, match="source_refs"):
        normalize_output_contract(
            {
                "contract_id": "c",
                "contract_version": "1",
                "source_refs": ["ok", 7],
            }
        )
    with pytest.raises(ValueError, match="structured_payload"):
        normalize_output_contract(
            {
                "contract_id": "c",
                "contract_version": "1",
                "structured_payload": ["not", "an", "object"],
            }
        )
    with pytest.raises(ValueError, match="must be an object"):
        normalize_output_contract(["not", "an", "object"])


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
