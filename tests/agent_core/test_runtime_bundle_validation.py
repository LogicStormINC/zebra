"""Trust-boundary and mutation regressions for native Bundle v1."""

import hashlib
import json
from typing import Any

import pytest
from agent_core.domain.runtime_bundle import (
    MAX_BUNDLE_BYTES,
    ArtifactPin,
    ResolvedRuntimeBundle,
    parse_runtime_bundle,
    seal_runtime_bundle,
)
from pydantic import ValidationError

from tests.agent_core.test_runtime_bundle import pin, valid_payload


def reject(payload: dict[str, Any], *, recompute_digest: bool = True) -> None:
    if recompute_digest:
        canonical = json.dumps(
            payload["manifest"], ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        payload["bundle_digest"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    with pytest.raises(ValueError, match="^INVALID_BUNDLE$") as error:
        parse_runtime_bundle(json.dumps(payload).encode())
    assert "private-canary" not in str(error.value)


def test_digest_covers_configuration_scope_assets_and_evidence() -> None:
    original = valid_payload()
    mutations = [
        ("scope", "environment", "other"),
        ("scope", "authority_issuer", "https://another.example"),
        ("domains", "instructions", "changed"),
        ("engine", "image", "changed"),
        ("build_evidence", "digest", "changed"),
    ]
    for group, name, value in mutations:
        payload = valid_payload()
        manifest = payload["manifest"]
        if group == "domains":
            manifest[group][name]["parameters"]["business_text"] = value
        elif group in ("engine", "build_evidence"):
            target = manifest[group][name] if group == "engine" else manifest[group][0]
            old = dict(target)
            target["digest"] = "sha256:" + "0" * 64
            manifest["lock"][manifest["lock"].index(old)] = dict(target)
        else:
            manifest[group][name] = value
        changed = seal_runtime_bundle(ResolvedRuntimeBundle.model_validate(manifest))
        assert changed.bundle_digest != original["bundle_digest"]
        reject(payload, recompute_digest=False)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "orphan",
        "duplicate",
        "conflict",
        "digest",
        "order",
        "evidence-duplicate",
        "evidence-kind",
    ],
)
def test_lock_is_exact_sorted_identity_unique_closure(mutation: str) -> None:
    payload = valid_payload()
    manifest = payload["manifest"]
    lock = manifest["lock"]
    if mutation == "missing":
        lock.pop()
    elif mutation == "orphan":
        lock.append(pin("build-evidence", "orphan"))
    elif mutation == "duplicate":
        lock.insert(0, dict(lock[0]))
    elif mutation == "conflict":
        lock.insert(0, {**lock[0], "version": "2.0.0"})
    elif mutation == "digest":
        lock[0]["digest"] = "sha256:" + "0" * 64
    elif mutation == "order":
        lock.reverse()
    elif mutation == "evidence-duplicate":
        manifest["build_evidence"].append(dict(manifest["build_evidence"][0]))
    else:
        manifest["build_evidence"][0] = manifest["engine"]["image"]
    reject(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("context_window_tokens", 0),
        ("context_window_tokens", 1_048_577),
        ("max_output_tokens", 0),
        ("max_output_tokens", 1_048_577),
        ("max_output_tokens", 1_048_576 + 1),
        ("max_retries", -1),
        ("max_retries", 4),
        ("temperature_milli", -1),
        ("temperature_milli", 2001),
        ("max_retries", True),
        ("max_retries", "1"),
        ("max_retries", 1.0),
        ("thinking", "unlimited"),
        ("thinking", None),
        ("model", " private-canary "),
        ("model", "https://private-canary.example"),
    ],
)
def test_model_configuration_strict_bounds(field: str, value: object) -> None:
    payload = valid_payload()
    payload["manifest"]["domains"]["model"]["parameters"][field] = value
    reject(payload)


def test_model_output_cannot_exceed_context() -> None:
    payload = valid_payload()
    payload["manifest"]["domains"]["model"]["parameters"].update(
        context_window_tokens=1,
        max_output_tokens=2,
    )
    reject(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("system_text", "x" * 32_769),
        ("business_text", "x" * 32_769),
        ("system_text", "\ud800"),
        ("business_text", "\udfff"),
        ("locale", " zh-CN"),
        ("locale", "zh_CN"),
        ("locale", "x" * 65),
        ("system_text", 123),
        ("business_text", None),
    ],
)
def test_instruction_configuration_bounded_without_normalization(field: str, value: object) -> None:
    payload = valid_payload()
    payload["manifest"]["domains"]["instructions"]["parameters"][field] = value
    reject(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-domain",
        "pinned-parameters",
        "pinned-reason",
        "configured-reason",
        "mode",
        "component",
        "catalog",
        "abi",
        "script",
        "future-manifest",
        "future-envelope",
        "unknown-field",
        "provider-kind",
        "output-kind",
        "image-kind",
        "baseline-kind",
        "extra-secret",
    ],
)
def test_no_fallback_for_unknown_or_changed_contract(mutation: str) -> None:
    payload = valid_payload()
    manifest = payload["manifest"]
    if mutation == "unknown-domain":
        manifest["domains"]["future"] = manifest["domains"]["engine"]
    elif mutation == "pinned-parameters":
        manifest["domains"]["policy"]["parameters"]["bypass"] = True
    elif mutation == "pinned-reason":
        manifest["domains"]["policy"]["reason"] = "enabled"
    elif mutation == "configured-reason":
        manifest["domains"]["model"]["reason"] = "supported"
    elif mutation == "mode":
        manifest["domains"]["model"]["mode"] = "pinned"
    elif mutation == "component":
        manifest["domains"]["tools"]["component"]["version"] = "2.0.0"
    elif mutation == "catalog":
        manifest["catalog_digest"] = "sha256:" + "0" * 64
    elif mutation in ("abi", "script"):
        manifest["engine"]["bundle_abi" if mutation == "abi" else "script_abi"] = "future/2"
    elif mutation in ("future-manifest", "future-envelope"):
        (manifest if mutation == "future-manifest" else payload)["schema_version"] = "future/2"
    elif mutation == "unknown-field":
        manifest["new_feature"] = "private-canary"
    elif mutation in ("provider-kind", "output-kind"):
        domain, field = (
            ("model", "provider_profile")
            if mutation == "provider-kind"
            else ("instructions", "output_schema")
        )
        manifest["domains"][domain]["parameters"][field]["kind"] = "component"
    elif mutation == "image-kind":
        manifest["engine"]["image"]["kind"] = "component"
    elif mutation == "baseline-kind":
        manifest["baseline_config"]["kind"] = "component"
    else:
        manifest["domains"]["model"]["parameters"]["api_key"] = "private-canary"
    reject(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "https://private-canary.example/image"),
        ("id", "a/../b"),
        ("id", "../a"),
        ("id", "a?credential=private-canary"),
        ("id", "user:password@image"),
        ("id", "a//b"),
        ("id", " a"),
        ("id", "a/"),
        ("id", "😀"),
        ("version", "latest"),
        ("version", "main"),
        ("version", "v1.0.0"),
        ("version", "01.0.0"),
        ("version", "1.0"),
        ("version", 1),
        ("digest", "SHA256:" + "0" * 64),
        ("digest", "sha256:" + "A" * 64),
        ("digest", "sha256:" + "0" * 63),
        ("digest", "sha256:" + "0" * 64 + " "),
        ("kind", "secret"),
    ],
)
def test_asset_pins_are_exact_locators(field: str, value: object) -> None:
    sample: dict[str, Any] = pin("image", "image/native")
    sample[field] = value
    with pytest.raises(ValidationError):
        ArtifactPin.model_validate(sample)


@pytest.mark.parametrize(
    "issuer",
    [
        "http://business.example",
        " https://business.example",
        "https://business.example\n",
        "https://user:private-canary@business.example",
        "https://business.example?private-canary",
        "https://business.example#fragment",
        "https://business.example?",
        "https://business.example#",
        "https://business.example:0",
        "https://business.example:65536",
        "https://business.example:",
        "https://business.example\x7f",
        "https://business.example\\other",
        "https://",
    ],
)
def test_authority_issuer_requires_unambiguous_https_without_credentials(issuer: str) -> None:
    payload = valid_payload()
    payload["manifest"]["scope"]["authority_issuer"] = issuer
    reject(payload)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b"null",
        b"true",
        b"\xef\xbb\xbf{}",
        b"\xff",
        b'"\xed\xa0\x80"',
        b'{"schema_version":"private-canary","schema_version":"second"}',
        b'{"unknown":{"same":1,"same":2}}',
        b'{"secret":"\\ud800"}',
        b'{"secret":"\\udfff"}',
        b'{"secret":1.0}',
        b'{"secret":1e1}',
        b'{"secret":NaN}',
        b'{"secret":Infinity}',
        b'{"secret":-Infinity}',
        b'{"secret":9223372036854775808}',
        b'{"secret":-9223372036854775809}',
        b"[" * 25 + b"0" + b"]" * 25,
        b"[" * 1100 + b"0" + b"]" * 1100,
        b"[" + b",".join([b"0"] * 8192) + b"]",
        b" " * (MAX_BUNDLE_BYTES + 1),
    ],
)
def test_hostile_json_is_bounded_and_errors_are_redacted(raw: bytes) -> None:
    with pytest.raises(ValueError, match="^INVALID_BUNDLE$"):
        parse_runtime_bundle(raw)


def test_canonical_expansion_is_bounded_too() -> None:
    payload = valid_payload()
    parameters = payload["manifest"]["domains"]["instructions"]["parameters"]
    parameters.update(system_text="你" * 32_768, business_text="好" * 32_768)
    # Raw UTF8 remains under the limit; canonical ASCII escapes exceed it.
    raw = json.dumps(payload, ensure_ascii=False).encode()
    assert len(raw) < MAX_BUNDLE_BYTES
    with pytest.raises(ValueError, match="^INVALID_BUNDLE$"):
        parse_runtime_bundle(raw)
    with pytest.raises(ValueError):
        seal_runtime_bundle(ResolvedRuntimeBundle.model_validate(payload["manifest"]))


def test_component_substitution_rejects_even_with_resealed_hash_and_closure() -> None:
    payload = valid_payload()
    manifest = payload["manifest"]
    before = dict(manifest["domains"]["engine"]["component"])
    changed = {**before, "digest": "sha256:" + "0" * 64}
    manifest["domains"]["engine"]["component"] = changed
    manifest["lock"][manifest["lock"].index(before)] = changed
    with pytest.raises(ValidationError):
        ResolvedRuntimeBundle.model_validate(manifest)


def test_json_budget_boundaries_are_enforced_before_schema_validation() -> None:
    from agent_core.domain.runtime_bundle_json import load_bundle_json

    # Scalar depth1, each enclosing list adds one; keys also count toward node budget.
    assert load_bundle_json(b"[" * 23 + b"0" + b"]" * 23) is not None
    with pytest.raises(ValueError, match="JSON limit exceeded"):
        load_bundle_json(b"[" * 24 + b"0" + b"]" * 24)
    assert len(load_bundle_json(b"[" + b",".join([b"0"] * 8191) + b"]")) == 8191
    with pytest.raises(ValueError, match="JSON limit exceeded"):
        load_bundle_json(b"[" + b",".join([b"0"] * 8192) + b"]")
    encoded = json.dumps(valid_payload()).encode()
    padded = encoded + b" " * (MAX_BUNDLE_BYTES - len(encoded))
    assert parse_runtime_bundle(padded).bundle_digest == valid_payload()["bundle_digest"]
    with pytest.raises(ValueError, match="^INVALID_BUNDLE$"):
        parse_runtime_bundle(padded + b" ")


def test_duplicate_keys_reject_even_when_valid_values_match() -> None:
    raw = json.dumps(valid_payload()).encode()
    duplicated = raw.replace(b'"max_retries": 3', b'"max_retries": 3, "max_retries": 3')
    assert duplicated != raw
    with pytest.raises(ValueError, match="^INVALID_BUNDLE$"):
        parse_runtime_bundle(duplicated)
