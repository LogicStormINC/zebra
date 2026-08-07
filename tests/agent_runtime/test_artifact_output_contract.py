import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.domain.events import EventType
from agent_core.harness import HarnessAttemptOutcome
from agent_runtime import LocalToolGateway, run_local_harness
from agent_runtime.artifact_output_contract import (
    ARTIFACT_OUTPUT_CONTRACT_EMIT_NAME,
)
from agent_security import PolicyProfile

NOW = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)


def _envelope() -> dict[str, object]:
    return {
        "contract_id": "finos.daily-trading-journal",
        "contract_version": "1",
        "structured_payload": {"business_date": "2026-08-04"},
        "payload_digest": "sha256:" + "f" * 64,
        "source_refs": ["broker:emit"],
    }


def test_local_gateway_registers_the_generic_emit_tool(tmp_path: Path) -> None:
    gateway = LocalToolGateway(tmp_path)
    names = {item.name for item in gateway.model_tools}
    assert ARTIFACT_OUTPUT_CONTRACT_EMIT_NAME in names


def test_emit_tool_executes_and_carries_the_envelope_in_metadata(
    tmp_path: Path,
) -> None:
    gateway = LocalToolGateway(tmp_path)
    envelope = _envelope()
    result = gateway.execute(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name=ARTIFACT_OUTPUT_CONTRACT_EMIT_NAME,
            arguments={"output_contract": envelope},
            created_at=NOW,
        )
    )
    assert result.status is ToolCallStatus.EXECUTED
    assert result.metadata["output_contract"] == envelope
    assert json.loads(result.output) == envelope


def test_emit_tool_executes_envelope_without_digest(tmp_path: Path) -> None:
    """The model may omit payload_digest entirely (FinOS computes it at save
    time); the tool must accept the four-field envelope."""
    gateway = LocalToolGateway(tmp_path)
    envelope = {
        "contract_id": "finos.daily-trading-journal",
        "contract_version": "1",
        "structured_payload": {"business_date": "2026-08-04"},
        "source_refs": ["broker:emit"],
    }
    result = gateway.execute(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name=ARTIFACT_OUTPUT_CONTRACT_EMIT_NAME,
            arguments={"output_contract": envelope},
            created_at=NOW,
        )
    )
    assert result.status is ToolCallStatus.EXECUTED
    assert result.metadata["output_contract"] == envelope


def test_emit_tool_rejects_incomplete_envelope(tmp_path: Path) -> None:
    gateway = LocalToolGateway(tmp_path)
    result = gateway.execute(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name=ARTIFACT_OUTPUT_CONTRACT_EMIT_NAME,
            arguments={
                "output_contract": {
                    "contract_id": "some.contract",
                    "contract_version": "1",
                }
            },
            created_at=NOW,
        )
    )
    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] in {
        "tool_validation_error",
        "invalid_output_contract",
    }


@pytest.mark.parametrize("profile", list(PolicyProfile))
def test_real_policy_engine_allows_emit_tool_in_local_harness(
    tmp_path: Path, profile: PolicyProfile
) -> None:
    """The real LocalPolicyEngine (not a test allow-all policy) must permit
    artifact.output_contract.emit under every local profile, so a real model
    run can complete the producer closed loop through the local harness."""
    envelope = _envelope()
    emit_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name=ARTIFACT_OUTPUT_CONTRACT_EMIT_NAME,
        arguments={"output_contract": envelope},
        created_at=NOW,
    )
    gateway = ScriptedModelGateway(
        (
            ScriptedModelResponse(
                ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="declaring the envelope",
                        created_at=NOW,
                    ),
                    tool_calls=(emit_call,),
                )
            ),
            ScriptedModelResponse(
                ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="final answer",
                        created_at=NOW,
                    )
                )
            ),
            ScriptedModelResponse(
                ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="final answer",
                        created_at=NOW,
                    )
                )
            ),
        )
    )
    result = run_local_harness(
        prompt="Declare the typed output envelope.",
        title="emit under real policy",
        workspace_root=tmp_path,
        model_gateway=gateway,
        policy_profile=profile,
        max_model_calls=4,
        max_tool_calls=2,
    )
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["output_contract"] == envelope
    model_events = [
        event
        for event in result.attempt_result.emitted_events
        if event.event_type is EventType.MODEL_RESPONSE_RECEIVED
    ]
    assert model_events[-1].payload["output_contract"] == envelope
