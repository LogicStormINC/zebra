from __future__ import annotations

import copy

import pytest

from scripts.validate_rollout_rehearsal import (
    PHASES,
    SCENARIOS,
    _canonical_digest,
    validate_rehearsal,
)


def _fixtures() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    candidate: dict[str, object] = {
        "candidate_id": "rc1",
        "capabilities": {
            "client_actions": "enabled",
            "redis_agent_memory": "not_enabled",
            "task_execution": "enabled",
        },
    }
    digest = _canonical_digest(candidate)
    attestation: dict[str, object] = {
        "schema_version": "zebra.cloud-rollout-attestation.v1",
        "status": "PASS",
        "candidate_sha256": digest,
    }
    metrics = {
        "authorization_errors": 0,
        "duplicate_effects": 0,
        "unresolved_mutations": 0,
        "lost_wakeups": 0,
    }
    phases = [
        {
            "name": name,
            "traffic_percent": traffic,
            "status": "PASS",
            "sample_count": 1,
            "metrics": metrics.copy(),
            "evidence_ref": f"evidence/{name}.json",
        }
        for name, traffic in PHASES
    ]
    scenarios = [
        {
            "id": scenario_id,
            "status": (
                "NOT_ENABLED" if scenario_id == "memory-delete" else "PASS"
            ),
            "evidence_ref": f"evidence/{scenario_id}.json",
        }
        for scenario_id in SCENARIOS
    ]
    rehearsal: dict[str, object] = {
        "schema_version": "zebra.cloud-rollout-rehearsal.v1",
        "candidate_sha256": digest,
        "environment": "staging",
        "phases": phases,
        "scenarios": scenarios,
    }
    return candidate, attestation, rehearsal


def test_complete_rehearsal_passes() -> None:
    candidate, attestation, rehearsal = _fixtures()

    verdict = validate_rehearsal(candidate, attestation, rehearsal)

    assert verdict["status"] == "PASS"
    assert verdict["scenario_count"] == len(SCENARIOS)


def test_enabled_memory_requires_real_evidence() -> None:
    candidate, attestation, rehearsal = _fixtures()
    candidate["capabilities"]["redis_agent_memory"] = "enabled"
    digest = _canonical_digest(candidate)
    attestation["candidate_sha256"] = digest
    rehearsal["candidate_sha256"] = digest

    with pytest.raises(ValueError, match="memory-delete must report PASS"):
        validate_rehearsal(candidate, attestation, rehearsal)


def test_rehearsal_rejects_correctness_failure() -> None:
    candidate, attestation, rehearsal = _fixtures()
    rehearsal = copy.deepcopy(rehearsal)
    rehearsal["phases"][1]["metrics"]["duplicate_effects"] = 1

    with pytest.raises(ValueError, match="canary has correctness failures"):
        validate_rehearsal(candidate, attestation, rehearsal)


def test_rehearsal_rejects_missing_rollback_scenario() -> None:
    candidate, attestation, rehearsal = _fixtures()
    rehearsal["scenarios"] = [
        item
        for item in rehearsal["scenarios"]
        if item["id"] != "application-rollback"
    ]

    with pytest.raises(ValueError, match="scenario set mismatch"):
        validate_rehearsal(candidate, attestation, rehearsal)


def _v2_fixtures():
    candidate, attestation, rehearsal = _fixtures()
    candidate["schema_version"] = "zebra.cloud-rollout-candidate.v2"
    digest = _canonical_digest(candidate)
    attestation.update(schema_version="zebra.cloud-rollout-attestation.v2", candidate_sha256=digest)
    rehearsal.update(schema_version="zebra.cloud-rollout-rehearsal.v2", candidate_sha256=digest)
    for item in rehearsal["scenarios"]:
        if item["id"] == "trench-browser-client-action":
            item["id"] = "host-browser-client-action"
    return candidate, attestation, rehearsal


def test_independent_rehearsal_requires_neutral_host_action():
    candidate, attestation, rehearsal = _v2_fixtures()
    assert validate_rehearsal(candidate, attestation, rehearsal)["schema_version"].endswith(".v2")
    for item in rehearsal["scenarios"]:
        if item["id"] == "host-browser-client-action":
            item["id"] = "trench-browser-client-action"
    with pytest.raises(ValueError, match="scenario set mismatch"):
        validate_rehearsal(candidate, attestation, rehearsal)


@pytest.mark.parametrize("scenario", [
    "application-rollback", "authority-revocation", "worker-crash-recovery",
    "duplicate-delivery", "event-stream-integrity", "gvisor-execution-cleanup",
])
def test_v2_preserves_security_recovery_and_runtime_gates(scenario):
    candidate, attestation, rehearsal = _v2_fixtures()
    rehearsal["scenarios"] = [item for item in rehearsal["scenarios"] if item["id"] != scenario]
    with pytest.raises(ValueError, match="scenario set mismatch"):
        validate_rehearsal(candidate, attestation, rehearsal)


def test_rehearsal_rejects_mixed_contract_versions():
    candidate, attestation, rehearsal = _v2_fixtures()
    attestation["schema_version"] = "zebra.cloud-rollout-attestation.v1"
    with pytest.raises(ValueError, match="attestation schema"):
        validate_rehearsal(candidate, attestation, rehearsal)
