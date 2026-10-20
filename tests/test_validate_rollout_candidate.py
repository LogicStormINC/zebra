from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_release_evidence import build_manifest
from scripts.validate_rollout_candidate import validate_candidate

ROOT = Path(__file__).parents[1]


def _digest(value: dict[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _fixtures(version: str = "v1") -> tuple[dict[str, object], dict[str, object]]:
    commit = "a" * 40
    image = "registry.example/app@sha256:" + "b" * 64
    previous = "registry.example/app@sha256:" + "c" * 64
    # Unit fixture only; release provenance is exercised separately via build_manifest.
    release: dict[str, object] = {
        "schema_version": "zebra.cloud-release-manifest.v1",
        "candidate_sha": commit,
        "status": "PASS",
        "gates": (
            [
                {
                    "gate": "trench-e2e",
                    "capability": "trench",
                    "status": "PASS",
                    "evidence_sha256": "f" * 64,
                }
            ]
            if version == "v1"
            else []
        ),
    }
    candidate: dict[str, object] = {
        "schema_version": "zebra.cloud-rollout-candidate.v1",
        "candidate_id": "2026-09-20-rc1",
        "zebra": {"commit": commit, "image": image},
        "trench": {
            "commit": "d" * 40,
            "api_image": image,
            "frontend_image": image,
        },
        "component_packages": {
            "@zebra-agent/contracts": "0.1.0",
            "@zebra-agent/ui-contracts": "0.1.0",
            "@zebra-agent/client-core": "0.1.0",
            "@zebra-agent/react": "0.1.0",
        },
        "database": {
            "zebra_schema": 58,
            "trench_revision": "3c4d5e6f7081",
            "backward_compatible": True,
        },
        "protocols": {
            "host_manifest_read": ["v1", "v2"],
            "host_manifest_write": "v2",
            "workspace_snapshot_read": ["v1", "v2"],
            "workspace_snapshot_write": "v2",
            "frontend_protocol": "v1",
            "memory_provider": "internal",
            "memory_route_version": "v1",
        },
        "config_digests": {"zebra": "e" * 64, "trench": "f" * 64},
        "release_manifest_sha256": _digest(release),
        "test_artifact_refs": ["evidence/release-manifest.json"],
        "capabilities": {
            "client_actions": "enabled",
            "redis_agent_memory": "not_enabled",
        },
        "rollout": [
            {"name": "internal", "traffic_percent": 0, "min_observation_seconds": 300},
            {"name": "canary", "traffic_percent": 5, "min_observation_seconds": 900},
            {"name": "full", "traffic_percent": 100, "min_observation_seconds": 1800},
        ],
        "rollback": {
            "zebra_image": previous,
            "trench_api_image": previous,
            "trench_frontend_image": previous,
            "disable_capabilities": ["client_actions"],
            "database_forward_compatible": True,
        },
    }
    if version == "v2":
        candidate["schema_version"] = "zebra.cloud-rollout-candidate.v2"
        del candidate["trench"]
        del candidate["database"]["trench_revision"]
        del candidate["config_digests"]["trench"]
        del candidate["rollback"]["trench_api_image"]
        del candidate["rollback"]["trench_frontend_image"]
    if version == "v2":
        candidate["capabilities"]["task_execution"] = "enabled"
        # Unit-only evidence identifiers: these are never release artifacts.
        inventory = json.loads((ROOT / "configs/cloud_release_gates.json").read_text())
        release["gates"] = [
            {
                "gate": gate["id"],
                "capability": gate["capability"],
                "status": "NOT_ENABLED"
                if gate["capability"] in {"trench", "redis_agent_memory"}
                else "PASS",
                "evidence_sha256": "e" * 64,
                "member_evidence_sha256": {member: "f" * 64 for member in gate.get("members", [])},
            }
            for gate in inventory["gates"]
        ]
        candidate["release_manifest_sha256"] = _digest(release)
    if version == "v1":
        # Joint evidence still requires Runtime safety/recovery gates, not only product E2E.
        inventory = json.loads((ROOT / "configs/cloud_release_gates.json").read_text())
        release["gates"].extend(
            {
                "gate": gate["id"],
                "capability": gate["capability"],
                "status": "NOT_ENABLED" if gate["capability"] == "redis_agent_memory" else "PASS",
                "evidence_sha256": "e" * 64,
                "member_evidence_sha256": {member: "f" * 64 for member in gate.get("members", [])},
            }
            for gate in inventory["gates"]
            if gate["capability"] != "trench"
        )
        candidate["release_manifest_sha256"] = _digest(release)
    return candidate, release


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_valid_candidate_is_attested(version: str) -> None:
    candidate, release = _fixtures(version)

    result = validate_candidate(candidate, release)

    assert result["schema_version"] == f"zebra.cloud-rollout-attestation.{version}"
    assert ("trench_commit" in result) == (version == "v1")
    assert result["status"] == "PASS"
    assert result["zebra_commit"] == "a" * 40
    assert result["component_packages"]["@zebra-agent/react"] == "0.1.0"
    assert len(result["candidate_sha256"]) == 64


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_cli_binds_exact_release_manifest_file(tmp_path: Path, version: str) -> None:
    candidate, release = _fixtures(version)
    release_path = tmp_path / "release.json"
    candidate_path = tmp_path / "candidate.json"
    output_path = tmp_path / "attestation.json"
    release_path.write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
    candidate["release_manifest_sha256"] = hashlib.sha256(release_path.read_bytes()).hexdigest()
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/validate_rollout_candidate.py"),
            "--candidate",
            str(candidate_path),
            "--release-manifest",
            str(release_path),
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(output_path.read_text())["status"] == "PASS"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda candidate, release: release.update(status="FAIL"), "must have PASS"),
        (
            lambda candidate, release: candidate.update(release_manifest_sha256="0" * 64),
            "placeholder digest",
        ),
        (
            lambda candidate, release: candidate["zebra"].update(image="registry/app:latest"),
            "pinned by sha256",
        ),
        (
            lambda candidate, release: candidate["rollout"][1].update(traffic_percent=25),
            "canary must use 5%",
        ),
        (
            lambda candidate, release: candidate["rollback"].update(
                database_forward_compatible=False
            ),
            "must not require a database down migration",
        ),
        (
            lambda candidate, release: candidate["component_packages"].update(
                {"@zebra-agent/react": "latest"}
            ),
            "exact semantic versions",
        ),
        (
            lambda candidate, release: candidate["component_packages"].update(
                {"@zebra-agent/react": "0.2.0"}
            ),
            "do not match source packages",
        ),
        (
            lambda candidate, release: candidate["zebra"].update(commit="0" * 40),
            "placeholder SHA",
        ),
        (
            lambda candidate, release: candidate["trench"].update(
                api_image="registry/app@sha256:" + "0" * 64
            ),
            "placeholder digest",
        ),
        (
            lambda candidate, release: candidate["config_digests"].update(zebra="0" * 64),
            "placeholder digest",
        ),
    ],
)
def test_candidate_fails_closed(mutation: object, message: str) -> None:
    candidate, release = _fixtures()
    candidate = copy.deepcopy(candidate)
    release = copy.deepcopy(release)
    assert callable(mutation)
    mutation(candidate, release)

    with pytest.raises(ValueError, match=message):
        validate_candidate(candidate, release)


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize(
    "section,key,value",
    [
        ("zebra", "image", "latest"),
        ("zebra", "commit", "b" * 40),
        ("database", "backward_compatible", False),
        ("config_digests", "zebra", "0" * 64),
        ("protocols", "host_manifest_write", "unreadable"),
        ("rollback", "zebra_image", "latest"),
        ("rollback", "database_forward_compatible", False),
        ("rollback", "disable_capabilities", ["unknown"]),
        ("capabilities", "client_actions", "maybe"),
    ],
)
def test_common_contracts_stay_strict(version, section, key, value):
    candidate, release = _fixtures(version)
    candidate[section][key] = value
    with pytest.raises(ValueError):
        validate_candidate(candidate, release)


@pytest.mark.parametrize(
    "section,key",
    [
        (None, "trench"),
        ("database", "trench_revision"),
        ("config_digests", "trench"),
        ("rollback", "trench_api_image"),
        ("rollback", "trench_frontend_image"),
    ],
)
def test_v1_still_requires_every_joint_coordinate(section, key):
    candidate, release = _fixtures()
    del (candidate if section is None else candidate[section])[key]
    with pytest.raises(ValueError):
        validate_candidate(candidate, release)


@pytest.mark.parametrize("status", [None, "NOT_ENABLED", "FAIL"])
def test_joint_candidate_requires_passing_trench_evidence(status):
    candidate, release = _fixtures()
    release["gates"] = (
        [] if status is None else [{"gate": "trench-e2e", "capability": "trench", "status": status}]
    )
    candidate["release_manifest_sha256"] = _digest(release)
    with pytest.raises(ValueError, match="trench-e2e"):
        validate_candidate(candidate, release)


def test_independent_candidate_rejects_enabled_joint_gate():
    candidate, release = _fixtures("v2")
    release["gates"] = [{"gate": "trench-e2e", "capability": "trench", "status": "PASS"}]
    candidate["release_manifest_sha256"] = _digest(release)
    with pytest.raises(ValueError, match="NOT_ENABLED"):
        validate_candidate(candidate, release)


@pytest.mark.parametrize("case", ["missing", "stale", "dirty", "failed", "valid"])
def test_joint_rollout_uses_evidence_builder_provenance(tmp_path, case):
    candidate, fixture_release = _fixtures()
    evidence = {
        "schema_version": "zebra.cloud-gate-result.v1",
        "gate": "trench-e2e",
        "candidate_sha": "old" if case == "stale" else candidate["zebra"]["commit"],
        "worktree_clean": case != "dirty",
        "status": "FAIL" if case == "failed" else "PASS",
    }
    path = tmp_path / "gate-result.json"
    path.write_text(json.dumps(evidence))
    release = build_manifest(
        gate_config={
            "schema_version": "zebra.cloud-release-gates.v1",
            "gates": [
                {"id": "trench-e2e", "level": "L5", "capability": "trench"},
            ],
        },
        capabilities={
            "schema_version": "zebra.cloud-release-capabilities.v1",
            "capabilities": {"trench": "enabled"},
        },
        evidence_paths=[] if case == "missing" else [path],
        candidate_sha=candidate["zebra"]["commit"],
    )
    release["gates"].extend(
        gate for gate in fixture_release["gates"] if gate["gate"] != "trench-e2e"
    )
    candidate["release_manifest_sha256"] = _digest(release)
    if case == "valid":
        assert validate_candidate(candidate, release)["status"] == "PASS"
    else:
        with pytest.raises(ValueError):
            validate_candidate(candidate, release)


@pytest.mark.parametrize("digest", [None, "0" * 64, "invalid"])
def test_joint_gate_requires_actual_evidence_digest(digest):
    candidate, release = _fixtures()
    release["gates"][0]["evidence_sha256"] = digest
    candidate["release_manifest_sha256"] = _digest(release)
    with pytest.raises(ValueError, match="trench-e2e evidence_sha256"):
        validate_candidate(candidate, release)


@pytest.mark.parametrize(
    "gate_id",
    [
        "cloud-contracts",
        "cloud-composition",
        "cloud-integration",
        "cloud-faults",
    ],
)
@pytest.mark.parametrize("status", [None, "NOT_ENABLED", "FAIL"])
def test_v2_cannot_skip_mandatory_gates(gate_id, status):
    candidate, release = _fixtures("v2")
    if status is None:
        release["gates"] = [gate for gate in release["gates"] if gate["gate"] != gate_id]
    else:
        next(gate for gate in release["gates"] if gate["gate"] == gate_id)["status"] = status
    candidate["release_manifest_sha256"] = _digest(release)
    with pytest.raises(ValueError, match=gate_id):
        validate_candidate(candidate, release)


def test_v2_rejects_empty_gates():
    candidate, release = _fixtures("v2")
    release["gates"] = []
    candidate["release_manifest_sha256"] = _digest(release)
    with pytest.raises(ValueError, match="cloud-contracts"):
        validate_candidate(candidate, release)


@pytest.mark.parametrize("capability", ["task_execution", "redis_agent_memory"])
def test_v2_requires_explicit_optional_capability(capability):
    candidate, release = _fixtures("v2")
    del candidate["capabilities"][capability]
    with pytest.raises(ValueError, match=capability):
        validate_candidate(candidate, release)


@pytest.mark.parametrize("gate_id", ["gvisor-runtime", "redis-agent-memory"])
def test_v2_optional_gate_status_matches_candidate(gate_id):
    candidate, release = _fixtures("v2")
    gate = next(gate for gate in release["gates"] if gate["gate"] == gate_id)
    gate["status"] = "NOT_ENABLED" if gate["status"] == "PASS" else "PASS"
    candidate["release_manifest_sha256"] = _digest(release)
    with pytest.raises(ValueError, match=gate_id):
        validate_candidate(candidate, release)


@pytest.mark.parametrize("gate_id", ["cloud-contracts", "cloud-integration", "gvisor-runtime"])
def test_v2_requires_enabled_gate_evidence_digests(gate_id):
    candidate, release = _fixtures("v2")
    gate = next(gate for gate in release["gates"] if gate["gate"] == gate_id)
    if gate_id == "cloud-integration":
        del gate["member_evidence_sha256"]["recovery-pitr"]
    else:
        gate["evidence_sha256"] = None
    candidate["release_manifest_sha256"] = _digest(release)
    with pytest.raises(ValueError, match=gate_id):
        validate_candidate(candidate, release)


def test_v2_accepts_complete_evidence_builder_output(tmp_path):
    candidate, _ = _fixtures("v2")
    inventory = json.loads((ROOT / "configs/cloud_release_gates.json").read_text())
    capabilities = json.loads(
        (ROOT / "configs/cloud_release_capabilities.example.json").read_text()
    )
    paths = []
    for gate in inventory["gates"]:
        if capabilities["capabilities"][gate["capability"]] == "not_enabled":
            continue
        for member in gate.get("members", [None]):
            # Temporary test envelopes exercise provenance validation; not release evidence.
            evidence = {
                "schema_version": (
                    "zebra.cloudline.runner-result.v1" if member else "zebra.cloud-gate-result.v1"
                ),
                "candidate_sha": candidate["zebra"]["commit"],
                "worktree_clean": True,
                **(
                    {"runner": member, "passed": True}
                    if member
                    else {"gate": gate["id"], "status": "PASS"}
                ),
            }
            path = tmp_path / f"{member or gate['id']}.json"
            path.write_text(json.dumps(evidence))
            paths.append(path)
    release = build_manifest(
        gate_config=inventory,
        capabilities=capabilities,
        evidence_paths=paths,
        candidate_sha=candidate["zebra"]["commit"],
    )
    candidate["release_manifest_sha256"] = _digest(release)
    assert validate_candidate(candidate, release)["status"] == "PASS"
    release["gates"] = [gate for gate in release["gates"] if gate["capability"] != "trench"]
    candidate["release_manifest_sha256"] = _digest(release)
    assert validate_candidate(candidate, release)["status"] == "PASS"


@pytest.mark.parametrize("include_gate", [False, True])
def test_v2_rejects_enabled_trench_capability(include_gate):
    candidate, release = _fixtures("v2")
    candidate["capabilities"]["trench"] = "enabled"
    if not include_gate:
        release["gates"] = [gate for gate in release["gates"] if gate["capability"] != "trench"]
    candidate["release_manifest_sha256"] = _digest(release)
    with pytest.raises(ValueError, match="Trench capability must be not_enabled"):
        validate_candidate(candidate, release)


@pytest.mark.parametrize(
    "gate_id",
    [
        "cloud-contracts",
        "cloud-composition",
        "cloud-integration",
        "cloud-faults",
    ],
)
@pytest.mark.parametrize("status", [None, "NOT_ENABLED", "FAIL"])
def test_joint_product_gate_cannot_replace_runtime_safety(gate_id, status):
    candidate, release = _fixtures()
    if status is None:
        release["gates"] = [gate for gate in release["gates"] if gate["gate"] != gate_id]
    else:
        next(gate for gate in release["gates"] if gate["gate"] == gate_id)["status"] = status
    candidate["release_manifest_sha256"] = _digest(release)
    with pytest.raises(ValueError, match=gate_id):
        validate_candidate(candidate, release)
