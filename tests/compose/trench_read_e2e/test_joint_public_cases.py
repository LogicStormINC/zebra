"""Public-path contract regressions are not successful live cases."""

from __future__ import annotations

import pytest
from joint_public_cases import public_prompt, validate_partial


def evidence():
    return {
        "scope": "real_scratch_host_browser_sse",
        "fixture_routes": False,
        "post_count": 1,
        "final_count": 1,
        "admission_terminal": False,
        "stream_open_before_terminal": True,
        "turn_id": "turn1",
        "case_id": "multi_source",
        "public_output_count": 1,
        "tool_count": 1,
        "public_visibility": [{"before_terminal": True, "before_final_receipt": True}],
        "frames": [
            {
                "cursor": 1,
                "type": "public_output",
                "meaningful": True,
                "evidence_basis": "verified_result",
                "coverage_qualified": True,
            }
        ],
        "cleanup": {"worker_cleanup": {"status": "passed"}, "answer_observed_to_cleanup_ms": 500},
        "timing": {
            "schemaVersion": "trench.strategy-timing.v1",
            "clock": "document.performance.now",
            "turns": [
                {
                    "turnId": "turn1",
                    "replay": False,
                    "submitAtMs": 0,
                    "admissionReceivedAtMs": 100,
                    "firstPublicTextReceiptAtMs": 200,
                    "finalCommitReceiptAtMs": 300,
                    "submitToAdmissionFeedbackMs": 100,
                }
            ],
            "events": [
                {
                    "turnId": "turn1",
                    "replay": False,
                    "backgrounded": False,
                    "coalesced": False,
                    "relayToPaintReadyMs": 15,
                }
            ],
        },
    }


def test_qualified_verified_fact_must_be_visible_before_terminal():
    data = evidence()
    validate_partial(data)
    data["public_visibility"][0]["before_terminal"] = False
    with pytest.raises(ValueError):
        validate_partial(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("meaningful", False),
        ("evidence_basis", "verified_work"),
        ("coverage_qualified", False),
    ],
)
def test_generic_status_or_unqualified_fact_is_not_partial_result(field, value):
    data = evidence()
    data["frames"][0][field] = value
    with pytest.raises(ValueError):
        validate_partial(data)


def test_partial_cannot_infer_cleanup_from_answer():
    data = evidence()
    data["cleanup"]["worker_cleanup"] = {"status": "not_proven"}
    with pytest.raises(ValueError):
        validate_partial(data)


def test_tool_only_prompt_requests_real_model_behavior_not_receipt_injection():
    prompt = public_prompt("tool_only", "marker", {"seed_id": "abc"})
    assert "工具调用前不要输出正文" in prompt
    assert "limit=20" in prompt and "12%" in prompt and "8%" in prompt
    with pytest.raises(ValueError, match="unimplemented"):
        public_prompt("revision", "marker", {"seed_id": "abc"})
