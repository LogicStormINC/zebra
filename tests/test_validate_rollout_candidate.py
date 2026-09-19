from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_rollout_candidate import validate_candidate

ROOT = Path(__file__).parents[1]


def _digest(value: dict[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _fixtures() -> tuple[dict[str, object], dict[str, object]]:
    commit = "a" * 40
    image = "registry.example/app@sha256:" + "b" * 64
    previous = "registry.example/app@sha256:" + "c" * 64
    release: dict[str, object] = {
        "schema_version": "zebra.cloud-release-manifest.v1",
        "candidate_sha": commit,
        "status": "PASS",
        "gates": [],
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
    return candidate, release


def test_valid_candidate_is_attested() -> None:
    candidate, release = _fixtures()

    result = validate_candidate(candidate, release)

    assert result["status"] == "PASS"
    assert result["zebra_commit"] == "a" * 40
    assert len(result["candidate_sha256"]) == 64


def test_cli_binds_exact_release_manifest_file(tmp_path: Path) -> None:
    candidate, release = _fixtures()
    release_path = tmp_path / "release.json"
    candidate_path = tmp_path / "candidate.json"
    output_path = tmp_path / "attestation.json"
    release_path.write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
    candidate["release_manifest_sha256"] = hashlib.sha256(
        release_path.read_bytes()
    ).hexdigest()
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
            "digest mismatch",
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
