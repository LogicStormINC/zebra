"""Offline check: public commentary survives replay and native wire serialization."""

import json
import sys
from pathlib import Path

from agent_core.domain.messages import MessageRole
from agent_core.domain.modeling import ModelCompletion
from agent_core.harness.model_step import HarnessModelStep
from agent_integrations.openai_payloads import serialize_message
from check_cloud_source_replay import conversation


def check(cases):
    for case in cases:
        context = {k: case[k] for k in ("goal", "cuts", "ack", "assistant_batches")}
        for index, cut in enumerate(case["cuts"]):
            corrected = conversation(case["rows"], cut, "A", **context)
            legacy = conversation(case["rows"], cut, "A", legacy=True, **context)
            assistants = [m for m in corrected if m.role == MessageRole.ASSISTANT]
            assert len(assistants) == index + 1
            assert len(legacy) == len(corrected) + 1
            for end, message in zip(case["cuts"][: index + 1], assistants, strict=True):
                assert message.content == case["assistant_batches"][str(end)]
                native = []
                HarnessModelStep.append_tool_batch(
                    native,
                    completion=ModelCompletion(assistant_message=message),
                    tool_calls=message.tool_calls,
                )
                wire = serialize_message(native[0], include_provider_reasoning=True)
                expected = message.content if message.content != "Tool calls proposed." else ""
                assert wire["content"] == expected
                assert len(wire["tool_calls"]) == len(message.tool_calls)
                assert wire["reasoning_content"] == ""
            # The fault concerns public assistant state; no tool evidence is changed.
            assert [m.content for m in corrected if m.role == MessageRole.TOOL] == [
                m.content for m in legacy if m.role == MessageRole.TOOL
            ]
    node = next(c for c in cases if c["name"] == "node")
    public_finding = node["assistant_batches"][str(node["cuts"][-1])]
    assert "2024-04-24" in public_finding and "2025-05-06" in public_finding
    print("PASS: native public commentary/call pairing/wire content; unchanged tool evidence")


if __name__ == "__main__":
    check(json.loads(Path(sys.argv[1]).read_text()))
