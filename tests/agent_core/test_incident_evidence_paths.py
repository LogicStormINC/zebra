import json

import pytest
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.harness.evidence_ledger import evidence_ledger, record_tool_evidence
from agent_core.harness.policy_step import recoverable_egress_denial
from agent_security import LocalPolicyEngine, PolicyProfile

from tests.agent_runtime.test_crawl_source_http import call

VIDEO = "https://www.bilibili.com/video/BV1pGnn67EbB"
POST = "https://t.bilibili.com/1260839262412079184"


def result(output, *, status=ToolCallStatus.EXECUTED, verified=True):
    return ToolResult(
        tool_call_id=call("events.read").tool_call_id,
        status=status,
        output=json.dumps(output),
        metadata={
            "read_only": True,
            "public_facts": {"evidence_basis": "verified_result"},
        }
        if verified
        else {},
    )


def test_source_body_link_is_observed_media_not_an_independent_source():
    state = record_tool_evidence(
        {},
        result(
            {
                "items": [
                    {
                        "original_url": POST,
                        "content_text": f"本期视频 {VIDEO}",
                        "videos": [],
                    }
                ]
            }
        ),
    )
    ledger = evidence_ledger([], state)
    assert VIDEO in ledger.media_refs
    assert ledger.evidence_refs == (POST,)
    assert "https://invented.test/video" not in ledger.media_refs
    assert not evidence_ledger(
        [],
        record_tool_evidence(
            {},
            result(
                {
                    "original_url": POST,
                    "content_text": VIDEO,
                },
                verified=False,
            ),
        ),
    ).media_refs


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"content_text": VIDEO}, ToolCallStatus.EXECUTED),
        ({"original_url": POST, "content_text": VIDEO}, ToolCallStatus.FAILED),
        ({"content_parts": [{"sourceUrl": VIDEO}]}, ToolCallStatus.EXECUTED),
        ({"original_url": POST, "content_text": "x" * 65536 + VIDEO}, ToolCallStatus.EXECUTED),
        (
            {"original_url": POST, "content_text": "https://user:secret@example.test/video"},
            ToolCallStatus.EXECUTED,
        ),
    ],
)
def test_media_needs_a_successful_bounded_source_record(payload, status):
    assert not evidence_ledger(
        [], record_tool_evidence({}, result(payload, status=status))
    ).media_refs


@pytest.mark.parametrize("path", ["", " ", 1])
def test_bad_read_path_is_nonexecuted_correctable_observation(path):
    request = call("files.search", query="NBOPC", path=path)
    decision = LocalPolicyEngine(PolicyProfile.FULL_ACCESS).evaluate_tool_call(request)
    observed = recoverable_egress_denial(
        request, decision, read_only_tools=frozenset({request.name})
    )
    assert observed is not None
    assert observed.metadata["executed"] is False
    assert observed.metadata["reason"] == "invalid_tool_arguments"


@pytest.mark.parametrize("path", ["../outside", "/etc/passwd", "docs/../secret"])
def test_real_path_escape_remains_a_hard_denial(path):
    request = call("files.search", query="NBOPC", path=path)
    decision = LocalPolicyEngine(PolicyProfile.FULL_ACCESS).evaluate_tool_call(request)
    assert decision.decision.value == "deny"
    assert (
        recoverable_egress_denial(request, decision, read_only_tools=frozenset({request.name}))
        is None
    )
