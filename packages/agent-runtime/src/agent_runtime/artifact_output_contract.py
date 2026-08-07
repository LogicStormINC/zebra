"""Producer-neutral generic artifact output-contract emission tool.

Any agent may explicitly emit a typed ``output_contract`` envelope for its
final answer. The tool does not know any specific contract, does not read
Skill names, titles or final text, and never triggers saving, data
confirmation or Core writes - it only declares generic metadata that is
bound to the final response by the harness.
"""

from __future__ import annotations

import json

from agent_core.domain.modeling import (
    ARTIFACT_OUTPUT_CONTRACT_EMIT_TOOL_NAME,
    normalize_output_contract,
)
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_tools import ToolContract


ARTIFACT_OUTPUT_CONTRACT_EMIT_NAME = ARTIFACT_OUTPUT_CONTRACT_EMIT_TOOL_NAME

ARTIFACT_OUTPUT_CONTRACT_EMIT_TOOL = ToolContract(
    name=ARTIFACT_OUTPUT_CONTRACT_EMIT_NAME,
    description=(
        "Declare generic typed artifact output metadata for the final answer. "
        "Pass contract_id, contract_version, structured_payload and "
        "source_refs. payload_digest is optional: FinOS derives the sha256 "
        "fingerprint when the journal is saved, so do NOT try to compute it "
        "and never run commands for it. This only declares metadata; it "
        "never saves anything."
    ),
    capability_version="artifact.output_contract.emit.v1",
    required_arguments=("output_contract",),
    argument_properties={
        "output_contract": {
            "type": "object",
            "properties": {
                "contract_id": {"type": "string", "minLength": 1},
                "contract_version": {"type": "string", "minLength": 1},
                "structured_payload": {"type": "object"},
                "payload_digest": {"type": "string"},
                "source_refs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
            },
            "required": [
                "contract_id",
                "contract_version",
                "structured_payload",
                "source_refs",
            ],
            "additionalProperties": False,
        }
    },
)


class ArtifactOutputContractEmitTool:
    contract: ToolContract = ARTIFACT_OUTPUT_CONTRACT_EMIT_TOOL

    def handle(self, call: ToolCall) -> ToolResult:
        envelope = call.arguments.get("output_contract")
        try:
            normalized = normalize_output_contract(envelope)
        except ValueError as exc:
            return ToolResult(
                tool_call_id=call.tool_call_id,
                status=ToolCallStatus.FAILED,
                metadata={
                    "reason": "invalid_output_contract",
                    "detail": str(exc)[:1000],
                },
            )
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=json.dumps(
                normalized, ensure_ascii=False, separators=(",", ":")
            ),
            metadata={
                "output_contract": normalized,
                "side_effect": "artifact_metadata",
            },
        )
