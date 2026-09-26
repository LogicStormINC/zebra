"""Validate an immutable cloud rollout candidate against release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
IMAGE_RE = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}")
VERSION_RE = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
)
PHASES = (("internal", 0), ("canary", 5), ("full", 100))
CAPABILITY_STATES = {"enabled", "not_enabled"}
COMPONENT_PACKAGES = {
    "@zebra-agent/client-core",
    "@zebra-agent/contracts",
    "@zebra-agent/react",
    "@zebra-agent/ui-contracts",
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _canonical_digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_component_versions() -> dict[str, str]:
    packages = ROOT / "sdks/typescript/packages"
    versions: dict[str, str] = {}
    for package in sorted(packages.glob("*/package.json")):
        payload = _read(package)
        name, version = payload.get("name"), payload.get("version")
        if isinstance(name, str) and name in COMPONENT_PACKAGES and isinstance(version, str):
            versions[name] = version
    return versions


def _require_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    missing = keys - value.keys()
    unknown = value.keys() - keys
    if missing or unknown:
        raise ValueError(f"{label} keys missing={sorted(missing)} unknown={sorted(unknown)}")


def _require_image(value: object, label: str) -> None:
    if not isinstance(value, str) or IMAGE_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be pinned by sha256 digest")
    if value.rsplit(":", 1)[-1] == "0" * 64:
        raise ValueError(f"{label} must not use a placeholder digest")


def _require_real_digest(value: object, label: str) -> None:
    if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a sha256 digest")
    if value == "0" * 64:
        raise ValueError(f"{label} must not use a placeholder digest")


def validate_candidate(
    candidate: dict[str, Any],
    release_manifest: dict[str, Any],
    *,
    release_manifest_digest: str | None = None,
    source_component_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    _require_keys(
        candidate,
        {
            "schema_version",
            "candidate_id",
            "zebra",
            "trench",
            "component_packages",
            "database",
            "protocols",
            "config_digests",
            "release_manifest_sha256",
            "test_artifact_refs",
            "capabilities",
            "rollout",
            "rollback",
        },
        "candidate",
    )
    if candidate["schema_version"] != "zebra.cloud-rollout-candidate.v1":
        raise ValueError("unsupported rollout candidate schema")
    if (
        not isinstance(candidate["candidate_id"], str)
        or not candidate["candidate_id"].strip()
        or candidate["candidate_id"].startswith("replace-with-")
    ):
        raise ValueError("candidate_id must be non-empty")
    if release_manifest.get("schema_version") != "zebra.cloud-release-manifest.v1":
        raise ValueError("unsupported release manifest schema")
    if release_manifest.get("status") != "PASS":
        raise ValueError("release manifest must have PASS status")
    expected_release_digest = candidate["release_manifest_sha256"]
    _require_real_digest(expected_release_digest, "release_manifest_sha256")
    actual_release_digest = release_manifest_digest or _canonical_digest(release_manifest)
    if expected_release_digest != actual_release_digest:
        raise ValueError("release manifest digest mismatch")

    zebra = candidate["zebra"]
    trench = candidate["trench"]
    if not isinstance(zebra, dict) or not isinstance(trench, dict):
        raise ValueError("zebra and trench coordinates must be objects")
    _require_keys(zebra, {"commit", "image"}, "zebra")
    _require_keys(trench, {"commit", "api_image", "frontend_image"}, "trench")
    if COMMIT_RE.fullmatch(str(zebra["commit"])) is None:
        raise ValueError("zebra.commit must be a full lowercase commit SHA")
    if zebra["commit"] == "0" * 40:
        raise ValueError("zebra.commit must not use a placeholder SHA")
    if zebra["commit"] != release_manifest.get("candidate_sha"):
        raise ValueError("zebra.commit does not match release candidate SHA")
    if COMMIT_RE.fullmatch(str(trench["commit"])) is None:
        raise ValueError("trench.commit must be a full lowercase commit SHA")
    if trench["commit"] == "0" * 40:
        raise ValueError("trench.commit must not use a placeholder SHA")
    _require_image(zebra["image"], "zebra.image")
    _require_image(trench["api_image"], "trench.api_image")
    _require_image(trench["frontend_image"], "trench.frontend_image")

    component_packages = candidate["component_packages"]
    if (
        not isinstance(component_packages, dict)
        or set(component_packages) != COMPONENT_PACKAGES
    ):
        raise ValueError("component_packages must freeze all public Zebra React SDK packages")
    if any(
        not isinstance(version, str) or VERSION_RE.fullmatch(version) is None
        for version in component_packages.values()
    ):
        raise ValueError("component package versions must be exact semantic versions")
    source_versions = source_component_versions or _source_component_versions()
    if component_packages != source_versions:
        raise ValueError("component package versions do not match source packages")

    database = candidate["database"]
    if not isinstance(database, dict):
        raise ValueError("database must be an object")
    _require_keys(
        database,
        {"zebra_schema", "trench_revision", "backward_compatible"},
        "database",
    )
    if not isinstance(database["zebra_schema"], int) or database["zebra_schema"] < 1:
        raise ValueError("database.zebra_schema must be a positive integer")
    if not isinstance(database["trench_revision"], str) or not database["trench_revision"]:
        raise ValueError("database.trench_revision must be non-empty")
    if database["backward_compatible"] is not True:
        raise ValueError("database migration must preserve rollback compatibility")

    protocols = candidate["protocols"]
    if not isinstance(protocols, dict):
        raise ValueError("protocols must be an object")
    _require_keys(
        protocols,
        {
            "host_manifest_read",
            "host_manifest_write",
            "workspace_snapshot_read",
            "workspace_snapshot_write",
            "frontend_protocol",
            "memory_provider",
            "memory_route_version",
        },
        "protocols",
    )
    for prefix in ("host_manifest", "workspace_snapshot"):
        readable = protocols[f"{prefix}_read"]
        writable = protocols[f"{prefix}_write"]
        if (
            not isinstance(readable, list)
            or not readable
            or any(not isinstance(value, str) or not value for value in readable)
            or not isinstance(writable, str)
            or writable not in readable
        ):
            raise ValueError(f"protocols.{prefix} write version must be readable")
    for key in ("frontend_protocol", "memory_provider", "memory_route_version"):
        if not isinstance(protocols[key], str) or not protocols[key]:
            raise ValueError(f"protocols.{key} must be non-empty")

    digests = candidate["config_digests"]
    if not isinstance(digests, dict) or set(digests) != {"zebra", "trench"}:
        raise ValueError("config_digests must contain only zebra and trench")
    for key, value in digests.items():
        _require_real_digest(value, f"config_digests.{key}")
    artifact_refs = candidate["test_artifact_refs"]
    if not isinstance(artifact_refs, list) or not artifact_refs or any(
        not isinstance(value, str) or not value.strip() for value in artifact_refs
    ):
        raise ValueError("test_artifact_refs must contain evidence locations")

    capabilities = candidate["capabilities"]
    if not isinstance(capabilities, dict) or not capabilities:
        raise ValueError("capabilities must be a non-empty object")
    if any(value not in CAPABILITY_STATES for value in capabilities.values()):
        raise ValueError("capabilities must be enabled or not_enabled")

    rollout = candidate["rollout"]
    if not isinstance(rollout, list) or len(rollout) != len(PHASES):
        raise ValueError("rollout must define internal, canary and full phases")
    for phase, (name, traffic) in zip(rollout, PHASES, strict=True):
        if not isinstance(phase, dict):
            raise ValueError("rollout phases must be objects")
        _require_keys(
            phase,
            {"name", "traffic_percent", "min_observation_seconds"},
            f"rollout.{name}",
        )
        if phase["name"] != name or phase["traffic_percent"] != traffic:
            raise ValueError(f"rollout phase {name} must use {traffic}% traffic")
        observation = phase["min_observation_seconds"]
        if not isinstance(observation, int) or observation < 60:
            raise ValueError(f"rollout phase {name} observation must be at least 60 seconds")

    rollback = candidate["rollback"]
    if not isinstance(rollback, dict):
        raise ValueError("rollback must be an object")
    _require_keys(
        rollback,
        {
            "zebra_image",
            "trench_api_image",
            "trench_frontend_image",
            "disable_capabilities",
            "database_forward_compatible",
        },
        "rollback",
    )
    for key in ("zebra_image", "trench_api_image", "trench_frontend_image"):
        _require_image(rollback[key], f"rollback.{key}")
    disabled = rollback["disable_capabilities"]
    if not isinstance(disabled, list) or not disabled or any(
        not isinstance(value, str) or value not in capabilities for value in disabled
    ):
        raise ValueError("rollback.disable_capabilities must name candidate capabilities")
    if rollback["database_forward_compatible"] is not True:
        raise ValueError("rollback must not require a database down migration")

    return {
        "schema_version": "zebra.cloud-rollout-attestation.v1",
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": _canonical_digest(candidate),
        "release_manifest_sha256": actual_release_digest,
        "zebra_commit": zebra["commit"],
        "trench_commit": trench["commit"],
        "component_packages": dict(sorted(component_packages.items())),
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        attestation = validate_candidate(
            _read(args.candidate),
            _read(args.release_manifest),
            release_manifest_digest=_file_digest(args.release_manifest),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ZEBRA_ROLLOUT_STATUS=FAIL REASON={exc}")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"ZEBRA_ROLLOUT_STATUS=PASS ATTESTATION={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
