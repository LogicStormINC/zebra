import json
from pathlib import Path

from scripts.build_release_evidence import build_manifest


def _gate_config() -> dict:
    return {
        "schema_version": "zebra.cloud-release-gates.v1",
        "gates": [
            {"id": "contracts", "level": "L1", "capability": "core"},
            {"id": "memory", "level": "L6", "capability": "memory"},
        ],
    }


def _capabilities() -> dict:
    return {
        "schema_version": "zebra.cloud-release-capabilities.v1",
        "capabilities": {"core": "enabled", "memory": "not_enabled"},
    }


def _evidence(path: Path, **overrides) -> Path:
    value = {
        "schema_version": "zebra.cloud-gate-result.v1",
        "gate": "contracts",
        "candidate_sha": "candidate",
        "worktree_clean": True,
        "status": "PASS",
    }
    value.update(overrides)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_release_manifest_separates_pass_and_not_enabled(tmp_path: Path) -> None:
    manifest = build_manifest(
        gate_config=_gate_config(),
        capabilities=_capabilities(),
        evidence_paths=[_evidence(tmp_path / "contracts.json")],
        candidate_sha="candidate",
    )

    assert manifest["status"] == "PASS"
    assert [gate["status"] for gate in manifest["gates"]] == ["PASS", "NOT_ENABLED"]


def test_enabled_gate_fails_closed_on_missing_stale_or_dirty_evidence(tmp_path: Path) -> None:
    for name, paths in (
        ("missing", []),
        ("stale", [_evidence(tmp_path / "stale.json", candidate_sha="old")]),
        ("dirty", [_evidence(tmp_path / "dirty.json", worktree_clean=False)]),
        ("failed", [_evidence(tmp_path / "failed.json", status="FAIL")]),
    ):
        manifest = build_manifest(
            gate_config=_gate_config(),
            capabilities=_capabilities(),
            evidence_paths=paths,
            candidate_sha="candidate",
        )

        assert manifest["status"] == "FAIL", name
        assert manifest["gates"][0]["status"] == "FAIL", name


def test_release_manifest_rejects_duplicate_gate_evidence(tmp_path: Path) -> None:
    first = _evidence(tmp_path / "first.json")
    second = _evidence(tmp_path / "second.json")

    try:
        build_manifest(
            gate_config=_gate_config(),
            capabilities=_capabilities(),
            evidence_paths=[first, second],
            candidate_sha="candidate",
        )
    except ValueError as error:
        assert "duplicate" in str(error)
    else:
        raise AssertionError("duplicate gate evidence must fail")


def test_member_gate_requires_every_clean_matching_cloudline_result(tmp_path: Path) -> None:
    gate_config = {
        "schema_version": "zebra.cloud-release-gates.v1",
        "gates": [
            {
                "id": "integration",
                "level": "L3",
                "capability": "cloud",
                "members": ["postgres", "redis"],
            }
        ],
    }
    capabilities = {
        "schema_version": "zebra.cloud-release-capabilities.v1",
        "capabilities": {"cloud": "enabled"},
    }
    paths = []
    for runner in ("postgres", "redis"):
        path = tmp_path / f"{runner}.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "zebra.cloudline.runner-result.v1",
                    "runner": runner,
                    "candidate_sha": "candidate",
                    "worktree_clean": True,
                    "passed": True,
                }
            ),
            encoding="utf-8",
        )
        paths.append(path)

    passed = build_manifest(
        gate_config=gate_config,
        capabilities=capabilities,
        evidence_paths=paths,
        candidate_sha="candidate",
    )
    missing = build_manifest(
        gate_config=gate_config,
        capabilities=capabilities,
        evidence_paths=paths[:1],
        candidate_sha="candidate",
    )

    assert passed["status"] == "PASS"
    assert passed["gates"][0]["member_evidence_sha256"].keys() == {"postgres", "redis"}
    assert missing["status"] == "FAIL"
