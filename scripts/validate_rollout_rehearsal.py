"""Validate G2/G3 rollout and rollback rehearsal evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

PHASES = (("internal", 0), ("canary", 5), ("full", 100))
SCENARIOS = {
    "postgres-recovery": None,
    "object-store-roundtrip": None,
    "message-wakeup": None,
    "trench-browser-client-action": "client_actions",
    "worker-crash-recovery": None,
    "duplicate-delivery": None,
    "timeout-recovery": None,
    "authority-revocation": None,
    "page-disconnect": "client_actions",
    "scheduler-wakeup": None,
    "memory-delete": "redis_agent_memory",
    "gvisor-execution-cleanup": "task_execution",
    "backup-restore": None,
    "forward-migration": None,
    "old-protocol-compatibility": None,
    "feature-disable": None,
    "application-rollback": None,
}
ZERO_METRICS = {
    "authorization_errors",
    "duplicate_effects",
    "unresolved_mutations",
    "lost_wakeups",
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _canonical_digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _require_evidence_ref(item: dict[str, Any], label: str) -> None:
    ref = item.get("evidence_ref")
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError(f"{label} must include a non-empty evidence_ref")


def validate_rehearsal(
    candidate: dict[str, Any],
    attestation: dict[str, Any],
    rehearsal: dict[str, Any],
) -> dict[str, Any]:
    if attestation.get("schema_version") != "zebra.cloud-rollout-attestation.v1":
        raise ValueError("unsupported rollout attestation schema")
    if attestation.get("status") != "PASS":
        raise ValueError("rollout attestation must have PASS status")
    candidate_digest = _canonical_digest(candidate)
    if attestation.get("candidate_sha256") != candidate_digest:
        raise ValueError("attestation does not bind this candidate")
    if rehearsal.get("schema_version") != "zebra.cloud-rollout-rehearsal.v1":
        raise ValueError("unsupported rollout rehearsal schema")
    if rehearsal.get("candidate_sha256") != candidate_digest:
        raise ValueError("rehearsal does not bind this candidate")
    environment = rehearsal.get("environment")
    if not isinstance(environment, str) or not environment.strip():
        raise ValueError("rehearsal environment must be non-empty")

    phases = rehearsal.get("phases")
    if not isinstance(phases, list) or len(phases) != len(PHASES):
        raise ValueError("rehearsal must record internal, canary and full phases")
    for phase, (name, traffic) in zip(phases, PHASES, strict=True):
        if not isinstance(phase, dict):
            raise ValueError("phase evidence must be an object")
        if phase.get("name") != name or phase.get("traffic_percent") != traffic:
            raise ValueError(f"phase {name} must record {traffic}% traffic")
        if phase.get("status") != "PASS":
            raise ValueError(f"phase {name} must pass before promotion")
        if not isinstance(phase.get("sample_count"), int) or phase["sample_count"] < 1:
            raise ValueError(f"phase {name} must include at least one sample")
        _require_evidence_ref(phase, f"phase {name}")
        metrics = phase.get("metrics")
        if not isinstance(metrics, dict) or set(metrics) != ZERO_METRICS:
            raise ValueError(f"phase {name} must include fixed correctness metrics")
        if any(metrics[key] != 0 for key in ZERO_METRICS):
            raise ValueError(f"phase {name} has correctness failures")

    scenario_items = rehearsal.get("scenarios")
    if not isinstance(scenario_items, list):
        raise ValueError("scenarios must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for item in scenario_items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("scenario evidence must have an id")
        if item["id"] in by_id:
            raise ValueError(f"duplicate scenario evidence: {item['id']}")
        by_id[item["id"]] = item
    if set(by_id) != set(SCENARIOS):
        raise ValueError(
            f"scenario set mismatch missing={sorted(set(SCENARIOS) - set(by_id))} "
            f"unknown={sorted(set(by_id) - set(SCENARIOS))}"
        )
    capabilities = candidate.get("capabilities")
    if not isinstance(capabilities, dict):
        raise ValueError("candidate capabilities are missing")
    for scenario_id, capability in SCENARIOS.items():
        item = by_id[scenario_id]
        expected = (
            "NOT_ENABLED"
            if capability is not None and capabilities.get(capability) == "not_enabled"
            else "PASS"
        )
        if item.get("status") != expected:
            raise ValueError(f"scenario {scenario_id} must report {expected}")
        if expected == "PASS":
            _require_evidence_ref(item, f"scenario {scenario_id}")

    return {
        "schema_version": "zebra.cloud-rollout-rehearsal-verdict.v1",
        "candidate_id": candidate.get("candidate_id"),
        "candidate_sha256": candidate_digest,
        "environment": environment,
        "phase_count": len(phases),
        "scenario_count": len(by_id),
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--rehearsal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        verdict = validate_rehearsal(
            _read(args.candidate), _read(args.attestation), _read(args.rehearsal)
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ZEBRA_REHEARSAL_STATUS=FAIL REASON={exc}")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"ZEBRA_REHEARSAL_STATUS=PASS VERDICT={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
