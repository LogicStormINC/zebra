"""Build a fail-closed release manifest from cloud gate result envelopes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _sha() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def build_manifest(
    *,
    gate_config: dict[str, Any],
    capabilities: dict[str, Any],
    evidence_paths: list[Path],
    candidate_sha: str,
) -> dict[str, Any]:
    if gate_config.get("schema_version") != "zebra.cloud-release-gates.v1":
        raise ValueError("unsupported gate configuration")
    if capabilities.get("schema_version") != "zebra.cloud-release-capabilities.v1":
        raise ValueError("unsupported capability configuration")
    states = capabilities.get("capabilities")
    if not isinstance(states, dict) or any(
        value not in {"enabled", "not_enabled"} for value in states.values()
    ):
        raise ValueError("capabilities must be enabled or not_enabled")
    evidence: dict[str, dict[str, Any]] = {}
    cloudline: dict[str, dict[str, Any]] = {}
    for path in evidence_paths:
        evidence_item = _read(path)
        schema = evidence_item.get("schema_version")
        if schema == "zebra.cloudline.runner-result.v1":
            runner = evidence_item.get("runner")
            if not isinstance(runner, str) or runner in cloudline:
                raise ValueError(f"duplicate or invalid cloudline evidence: {path}")
            cloudline[runner] = evidence_item
            continue
        if schema != "zebra.cloud-gate-result.v1":
            raise ValueError(f"unsupported gate evidence: {path}")
        gate_id = evidence_item.get("gate")
        if not isinstance(gate_id, str) or gate_id in evidence:
            raise ValueError(f"duplicate or invalid gate evidence: {path}")
        evidence[gate_id] = evidence_item
    results: list[dict[str, Any]] = []
    failures = 0
    for gate in gate_config.get("gates", []):
        gate_id = gate["id"]
        capability = gate["capability"]
        state = states.get(capability)
        candidate_item = evidence.get(gate_id)
        members = gate.get("members")
        if state == "not_enabled":
            status, reason = "NOT_ENABLED", "capability disabled in candidate manifest"
        elif state != "enabled":
            status, reason = "FAIL", "capability state missing"
        elif isinstance(members, list):
            missing = [member for member in members if member not in cloudline]
            invalid = [
                member
                for member in members
                if member in cloudline
                and (
                    cloudline[member].get("passed") is not True
                    or cloudline[member].get("candidate_sha") != candidate_sha
                    or cloudline[member].get("worktree_clean") is not True
                )
            ]
            if missing or invalid:
                status = "FAIL"
                reason = f"cloudline missing={missing} invalid={invalid}"
            else:
                status, reason = "PASS", None
        elif candidate_item is None:
            status, reason = "FAIL", "required evidence missing"
        elif candidate_item.get("candidate_sha") != candidate_sha:
            status, reason = "FAIL", "evidence candidate SHA mismatch"
        elif candidate_item.get("worktree_clean") is not True:
            status, reason = "FAIL", "evidence was collected from a dirty worktree"
        elif candidate_item.get("status") != "PASS":
            status, reason = "FAIL", f"gate reported {candidate_item.get('status')}"
        else:
            status, reason = "PASS", None
        failures += status == "FAIL"
        results.append(
            {
                "gate": gate_id,
                "level": gate["level"],
                "capability": capability,
                "status": status,
                "reason": reason,
                "evidence_sha256": (
                    hashlib.sha256(
                        json.dumps(
                            candidate_item, sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest()
                    if candidate_item is not None
                    else None
                ),
                "member_evidence_sha256": (
                    {
                        member: hashlib.sha256(
                            json.dumps(
                                cloudline[member], sort_keys=True, separators=(",", ":")
                            ).encode()
                        ).hexdigest()
                        for member in members
                        if member in cloudline
                    }
                    if isinstance(members, list)
                    else None
                ),
            }
        )
    return {
        "schema_version": "zebra.cloud-release-manifest.v1",
        "candidate_sha": candidate_sha,
        "status": "PASS" if failures == 0 else "FAIL",
        "gates": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gate-config", type=Path, default=ROOT / "configs/cloud_release_gates.json"
    )
    parser.add_argument("--capabilities", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--evidence-root", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = list(args.evidence)
    for root in args.evidence_root:
        paths.extend(sorted(root.glob("**/gate-result.json")))
        paths.extend(sorted(root.glob("**/result.json")))
    manifest = build_manifest(
        gate_config=_read(args.gate_config),
        capabilities=_read(args.capabilities),
        evidence_paths=paths,
        candidate_sha=_sha(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"ZEBRA_RELEASE_STATUS={manifest['status']} MANIFEST={args.output}")
    return 0 if manifest["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
