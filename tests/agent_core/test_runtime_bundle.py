"""Native Runtime Bundle contract, independent of historical Definition contracts."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from agent_core.domain.runtime_bundle import (
    ArtifactPin,
    ResolvedRuntimeBundle,
    RuntimeBundleEnvelope,
    RuntimeDomains,
    builtin_component_pin,
    canonical_runtime_bundle_bytes,
    parse_runtime_bundle,
    require_bundle_compatibility,
    runtime_bundle_catalog,
    runtime_bundle_catalog_digest,
    runtime_bundle_json_schema,
    seal_runtime_bundle,
)
from pydantic import ValidationError


def pin(kind: str, name: str) -> dict[str, str]:
    return {
        "kind": kind,
        "id": name,
        "version": "1.0.0",
        "digest": "sha256:" + hashlib.sha256(name.encode()).hexdigest(),
    }


def valid_payload() -> dict[str, Any]:
    """Fully declared, deterministic envelope used by offline golden generation."""
    image = pin("image", "cloud-agent/runtime")
    baseline = pin("baseline-config", "baseline/native")
    provider = pin("provider-profile", "providers/example")
    output = pin("output-schema", "output/answer")
    evidence = pin("build-evidence", "evidence/declared-source")
    domains: dict[str, Any] = {}
    components = []
    for name in RuntimeDomains.model_fields:
        component = builtin_component_pin(name).model_dump(mode="json")
        components.append(component)
        domains[name] = {
            "component": component,
            "mode": "pinned",
            "reason": "requires-runtime-assembly",
            "parameters": {},
        }
    domains["model"] = {
        "component": domains["model"]["component"],
        "mode": "configurable",
        "parameters": {
            "provider_profile": provider,
            "model": "example/model-1",
            "context_window_tokens": 1_048_576,
            "max_output_tokens": 1,
            "max_retries": 3,
            "temperature_milli": 2000,
            "thinking": "auto",
        },
    }
    domains["instructions"] = {
        "component": domains["instructions"]["component"],
        "mode": "configurable",
        "parameters": {
            "system_text": '你好 Zebra 😀\n"quoted"\\path\t',
            "business_text": "Preserve exact text. ",
            "locale": "zh-CN",
            "output_schema": output,
        },
    }
    manifest = ResolvedRuntimeBundle.model_validate(
        {
            "schema_version": "cloud-agent.runtime-bundle/1",
            "scope": {
                "authority_issuer": "https://business.example",
                "namespace_id": "tenant/example",
                "product_id": "product-a",
                "environment": "test",
                "target_id": "target/native",
                "deployment_id": "deployment/declared",
            },
            "engine": {
                "kind": "cloud-agent",
                "image": image,
                "bundle_abi": "cloud-agent.bundle/1",
                "script_abi": "unsupported",
            },
            "baseline_config": baseline,
            "catalog_digest": runtime_bundle_catalog_digest(),
            "domains": domains,
            "build_evidence": [evidence],
            "lock": sorted(
                [*components, image, baseline, provider, output, evidence],
                key=lambda item: (item["kind"], item["id"], item["version"]),
            ),
        }
    )
    return seal_runtime_bundle(manifest).model_dump(mode="json")


def test_catalog_declares_exact_native_domains_and_existing_sources() -> None:
    catalog = runtime_bundle_catalog()
    assert {item["domain"] for item in catalog["components"]} == set(RuntimeDomains.model_fields)
    root = Path(__file__).resolve().parents[2]
    for descriptor in catalog["components"]:
        for source in descriptor["source_refs"]:
            assert (root / source).is_file()
        digest = descriptor.pop("digest")
        encoded = json.dumps(descriptor, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        assert digest == "sha256:" + hashlib.sha256(encoded.encode("ascii")).hexdigest()
    assert len({builtin_component_pin(name).digest for name in RuntimeDomains.model_fields}) == 20


def test_catalog_and_schema_have_no_mutable_authoritative_state() -> None:
    before = runtime_bundle_catalog_digest()
    catalog = runtime_bundle_catalog()
    catalog["components"][0]["parameters_schema"]["properties"]["injected"] = {}
    assert runtime_bundle_catalog_digest() == before
    schema = runtime_bundle_json_schema()
    schema["$defs"]["RuntimeDomains"]["required"].clear()
    assert len(runtime_bundle_json_schema()["$defs"]["RuntimeDomains"]["required"]) == 20
    with pytest.raises(ValueError):
        builtin_component_pin("custom")


def test_seal_roundtrip_exact_canonical_profile() -> None:
    payload = valid_payload()
    envelope = parse_runtime_bundle(json.dumps(payload, ensure_ascii=False).encode())
    canonical = canonical_runtime_bundle_bytes(envelope.manifest)
    assert canonical.isascii()
    assert b"\\u4f60\\u597d" in canonical
    assert b"\\ud83d\\ude00" in canonical
    assert b'\\n\\"quoted\\"\\\\path\\t' in canonical
    assert envelope.bundle_digest == "sha256:" + hashlib.sha256(canonical).hexdigest()
    reordered = dict(reversed(list(payload.items())))
    assert parse_runtime_bundle(json.dumps(reordered, indent=4).encode()) == envelope
    assert seal_runtime_bundle(envelope.manifest) == envelope
    assert envelope.manifest.domains.instructions.parameters.business_text.endswith(" ")


def test_models_and_nested_sequences_are_frozen_and_detached() -> None:
    original = valid_payload()
    envelope = RuntimeBundleEnvelope.model_validate(original)
    original["manifest"]["domains"]["instructions"]["parameters"]["system_text"] = "changed"
    assert envelope.manifest.domains.instructions.parameters.system_text.startswith("你好")
    assert isinstance(envelope.manifest.lock, tuple)
    assert isinstance(envelope.manifest.build_evidence, tuple)
    with pytest.raises(ValidationError):
        envelope.manifest.domains.model.parameters.max_retries = 0
    with pytest.raises(ValidationError):
        envelope.manifest.domains.policy.parameters.injected = "config"
    with pytest.raises(ValidationError):
        envelope.manifest.lock[0].digest = "sha256:" + "0" * 64


def test_compatibility_requires_explicit_reader_abi_and_all_descriptors() -> None:
    envelope = RuntimeBundleEnvelope.model_validate(valid_payload())
    digests = frozenset(builtin_component_pin(name).digest for name in RuntimeDomains.model_fields)
    require_bundle_compatibility(
        envelope,
        supported_bundle_abis=frozenset({"cloud-agent.bundle/1"}),
        supported_component_digests=digests,
    )
    for abis, components in (
        (frozenset(), digests),
        (frozenset({"cloud-agent.bundle/1"}), frozenset(sorted(digests)[1:])),
    ):
        with pytest.raises(ValueError, match="^INCOMPATIBLE_BUNDLE$"):
            require_bundle_compatibility(
                envelope,
                supported_bundle_abis=abis,
                supported_component_digests=components,
            )


@pytest.mark.parametrize(
    "field",
    [
        "scope",
        "engine",
        "baseline_config",
        "domains",
        "lock",
        "build_evidence",
        "catalog_digest",
        "schema_version",
    ],
)
def test_manifest_fields_required(field: str) -> None:
    payload = valid_payload()["manifest"]
    del payload[field]
    with pytest.raises(ValidationError):
        ResolvedRuntimeBundle.model_validate(payload)


@pytest.mark.parametrize("domain", list(RuntimeDomains.model_fields))
def test_every_domain_required(domain: str) -> None:
    payload = valid_payload()["manifest"]
    del payload["domains"][domain]
    with pytest.raises(ValidationError):
        ResolvedRuntimeBundle.model_validate(payload)


def test_revalidate_constructed_or_copied_instances_before_hash_and_compatibility() -> None:
    valid = RuntimeBundleEnvelope.model_validate(valid_payload())
    unsafe = valid.manifest.model_copy(update={"catalog_digest": "sha256:" + "0" * 64})
    for operation in (canonical_runtime_bundle_bytes, seal_runtime_bundle):
        with pytest.raises(ValueError):
            operation(unsafe)
    with pytest.raises(ValueError):
        require_bundle_compatibility(
            valid.model_copy(update={"manifest": unsafe}),
            supported_bundle_abis=frozenset({"cloud-agent.bundle/1"}),
            supported_component_digests=frozenset(),
        )


def test_pin_requires_all_fields_and_rejects_extra_config() -> None:
    sample = pin("image", "native/image")
    for key in sample:
        with pytest.raises(ValidationError):
            ArtifactPin.model_validate(
                {name: value for name, value in sample.items() if name != key}
            )
    with pytest.raises(ValidationError):
        ArtifactPin.model_validate({**sample, "endpoint": "https://private.example"})
