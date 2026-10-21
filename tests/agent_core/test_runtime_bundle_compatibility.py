"""Published bytes and untouched legacy Definition/Snapshot v1 compatibility."""

from __future__ import annotations

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from agent_core.domain.agent_definition_snapshots import (
    AgentDefinitionSnapshot,
    canonical_agent_definition_snapshot_digest,
)
from agent_core.domain.agent_definitions import (
    AgentDefinitionVersion,
    AgentRelease,
    canonical_agent_definition_digest,
)
from agent_core.domain.runtime_bundle import (
    canonical_runtime_bundle_bytes,
    parse_runtime_bundle,
    runtime_bundle_catalog,
    runtime_bundle_json_schema,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/contracts/runtime-bundle-v1"
LEGACY = ROOT / "tests/fixtures/runtime_bundle_v1/legacy-v1.json"


def test_published_generated_artifacts_match_native_producer() -> None:
    assert runtime_bundle_json_schema() == json.loads(
        (CONTRACT / "envelope.schema.json").read_text()
    )
    assert runtime_bundle_catalog() == json.loads((CONTRACT / "component-catalog.json").read_text())
    # Mutating a discovery result must not change the native allowlist for any reader.
    runtime_bundle_catalog().clear()
    assert runtime_bundle_catalog() == json.loads((CONTRACT / "component-catalog.json").read_text())


def test_manifest_canonical_bytes_and_cross_language_vectors() -> None:
    example = json.loads((CONTRACT / "example-envelope.json").read_text())
    baseline = parse_runtime_bundle(json.dumps(example).encode())
    assert (
        canonical_runtime_bundle_bytes(baseline.manifest)
        == (CONTRACT / "manifest.canonical.json").read_bytes()
    )
    vectors = json.loads((CONTRACT / "digest-vectors.json").read_text())
    for vector in vectors["vectors"]:
        payload = copy.deepcopy(example)
        for name, value in vector["model_parameters"].items():
            payload["manifest"]["domains"]["model"]["parameters"][name] = value
        for name, value in vector["instruction_parameters"].items():
            payload["manifest"]["domains"]["instructions"]["parameters"][name] = value
        payload["bundle_digest"] = vector["bundle_digest"]
        # Both key ordering and insignificant whitespace differ from the published wire.
        wire = json.dumps(payload, ensure_ascii=False, indent=3).encode()
        parsed = parse_runtime_bundle(wire)
        canonical = canonical_runtime_bundle_bytes(parsed.manifest)
        assert len(canonical) == vector["canonical_byte_length"]
        assert "sha256:" + hashlib.sha256(canonical).hexdigest() == vector["bundle_digest"]
        assert canonical.isascii()


def test_parallel_validation_has_no_shared_mutable_state() -> None:
    raw = (CONTRACT / "example-envelope.json").read_bytes()
    with ThreadPoolExecutor(max_workers=4) as pool:
        digests = tuple(pool.map(lambda _: parse_runtime_bundle(raw).bundle_digest, range(16)))
    assert len(set(digests)) == 1
    # This checks deterministic concurrent calls only; it is not a load/HA benchmark.


def test_old_v1_roundtrip_and_digests_are_exactly_preserved() -> None:
    historical = json.loads(LEGACY.read_text())
    version = AgentDefinitionVersion.model_validate(historical["version"])
    release = AgentRelease.model_validate(historical["release"])
    assert version.model_dump(mode="json") == historical["version"]
    assert release.model_dump(mode="json") == historical["release"]
    assert canonical_agent_definition_digest(version) == historical["definition_digest"]
    for original, digest in zip(
        historical["snapshots"], historical["snapshot_digests"], strict=True
    ):
        snapshot = AgentDefinitionSnapshot.model_validate(original)
        assert snapshot.model_dump(mode="json") == original
        assert canonical_agent_definition_snapshot_digest(snapshot) == digest
    assert (
        AgentDefinitionSnapshot.from_version(
            version=version,
            resolved_at=AgentDefinitionSnapshot.model_validate(
                historical["snapshots"][0]
            ).resolved_at,
        ).snapshot_digest
        == historical["snapshot_digests"][0]
    )
    assert (
        AgentDefinitionSnapshot.from_release(
            version=version,
            release=release,
            resolved_at=AgentDefinitionSnapshot.model_validate(
                historical["snapshots"][1]
            ).resolved_at,
        ).snapshot_digest
        == historical["snapshot_digests"][1]
    )


def test_new_and_legacy_formats_are_not_silently_interpreted() -> None:
    historical = json.loads(LEGACY.read_text())
    with pytest.raises(ValueError):
        parse_runtime_bundle(json.dumps(historical["version"]).encode())
    with pytest.raises(ValueError):
        parse_runtime_bundle(json.dumps(historical["snapshots"][0]).encode())
    example = json.loads((CONTRACT / "example-envelope.json").read_text())
    for model in (AgentDefinitionVersion, AgentDefinitionSnapshot):
        with pytest.raises(ValidationError):
            model.model_validate(example)
    drift = {**historical["version"], "model_policy_ref": "model-policy/different@1"}
    with pytest.raises(ValidationError, match="does not match"):
        AgentDefinitionVersion.model_validate(drift)


def test_published_negative_vectors_reject_with_valid_outer_digests() -> None:
    example = json.loads((CONTRACT / "example-envelope.json").read_text())
    vectors = json.loads((CONTRACT / "negative-vectors.json").read_text())
    assert len(vectors["cases"]) >= 10
    for case in vectors["cases"]:
        candidate = copy.deepcopy(example)
        for patch in case["patches"]:
            target = candidate
            for segment in patch["path"][:-1]:
                target = target[segment]
            target[patch["path"][-1]] = patch["value"]
        # Independent encoding permits invalid candidate types; native validation must reject
        # their actual semantic violation, rather than succeeding on a stale hash mismatch.
        raw_manifest = json.dumps(
            candidate["manifest"], ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        candidate["bundle_digest"] = "sha256:" + hashlib.sha256(raw_manifest).hexdigest()
        with pytest.raises(ValueError, match=f"^{case['expected_error']}$"):
            parse_runtime_bundle(json.dumps(candidate).encode())
