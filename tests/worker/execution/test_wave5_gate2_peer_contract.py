"""Frozen cross-repo contract fixture for the FinOS peer (Wave 5 Gate 2)."""

import json
from pathlib import Path

from agent_core.contracts import validate_event_payload
from agent_core.domain.events import EventType


def test_wave5_gate2_peer_contract_fixture_validates() -> None:
    fixture_path = (
        Path(__file__).parents[2] / "fixtures" / "wave5_gate2_contract_delta_v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == "zebra-wave5-gate2-contract-delta-v1"
    classification = fixture["coverage_classification"]
    assert classification["retryable_after_bounded_correction"] == (
        "completion_evidence_missing_after_correction"
    )
    assert classification["non_retryable_without_correction"] == (
        "completion_evidence_missing"
    )
    assert classification["correction_requires_matching_advertised_producer"] is True
    assert classification["no_producer_behavior"] == (
        "no correction dispatch; one initial model call only; "
        "completion_evidence_missing; no Attempt 2"
    )
    for item in fixture["events"]:
        event_type = EventType(item["event_type"])
        if event_type in {
            EventType.TASK_PREPARED,
            EventType.HARNESS_ATTEMPT_STARTED,
            EventType.MODEL_RESPONSE_RECEIVED,
            EventType.ATTEMPT_OUTCOME_RECORDED,
        }:
            validate_event_payload(event_type, item["payload"])
    outcomes = [
        item["payload"]
        for item in fixture["events"]
        if item["event_type"] == "attempt_outcome_recorded"
    ]
    assert [outcome["retry_scheduled"] for outcome in outcomes] == [True, False]
    assert [outcome["terminal_reason"] for outcome in outcomes] == [
        "completion_evidence_missing_after_correction",
        "completion_evidence_missing_after_correction",
    ]
    assert outcomes[0]["result_metadata"]["completion_evidence_required_count"] == 1
    failed = next(
        item["payload"]
        for item in fixture["events"]
        if item["event_type"] == "session_failed"
    )
    assert failed["attempt_number"] == 2
    assert failed["retryable"] is False
    assert set(failed["coverage_verdict"]) == {
        "status",
        "required_count",
        "satisfied_count",
        "missing_count",
        "message",
    }
    assert fixture["public_boundary"]["terminal_coverage_verdict"] == [
        "status",
        "required_count",
        "satisfied_count",
        "missing_count",
        "message",
    ]
    assert fixture["public_boundary"]["coverage_verdict_sanitized"] is True
    assert fixture["public_boundary"]["malformed_verdict_policy"] == (
        "fail_closed_omit_or_rebuild_valid_safe_verdict"
    )
    assert "completion_evidence_missing" in fixture["public_boundary"][
        "private_fields_excluded_from_public_projection"
    ]
