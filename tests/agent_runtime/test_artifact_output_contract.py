import json
from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import LocalToolGateway
from agent_runtime.artifact_output_contract import (
    ARTIFACT_OUTPUT_CONTRACT_EMIT_NAME,
)

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
