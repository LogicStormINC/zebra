"""Published native producer bytes and portable executable/rejection vectors."""

import json
from pathlib import Path

import pytest
from agent_core.domain.runtime_assembly import RuntimeAssembly
from agent_core.domain.runtime_bundle import parse_runtime_bundle
from agent_core.domain.runtime_bundle_json import json_digest
from zebra_agent_config.bundle_settings import RuntimeExecutionCatalog

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "docs/contracts/bundle-validation-v1"


def read(name):
    return json.loads((ARTIFACTS / name).read_text())


def test_published_native_contract_exactly_matches_producer():
    from zebra_agent_api.bundle_management_contract import (
        bundle_contract_digest,
        native_bundle_contract,
    )

    contract = read("contract.json")
    assert contract == native_bundle_contract()
    assert contract["contractDigest"] == bundle_contract_digest()
    assert contract["contractDigest"] == json_digest(
        {key: value for key, value in contract.items() if key != "contractDigest"}
    )
    assert contract["envelopeSchema"] == json.loads(
        (ROOT / "docs/contracts/runtime-bundle-v1/envelope.schema.json").read_text()
    )
    assert contract["componentCatalog"] == json.loads(
        (ROOT / "docs/contracts/runtime-bundle-v1/component-catalog.json").read_text()
    )
    # Mutating a consumer copy cannot change later clients or the producer pin.
    original_digest = bundle_contract_digest()
    native_bundle_contract()["execution"]["thinking"] = "changed"
    native_bundle_contract()["execution"]["outputSchema"]["format"] = "changed"
    assert bundle_contract_digest() == original_digest


def test_openapi_covers_real_transport_and_fixed_failures():
    api = read("openapi.json")
    assert api["openapi"] == "3.1.0"
    endpoints = {
        "/management/v1/bundle-contract": "get",
        "/management/v1/bundle-validation": "post",
    }
    for path, method in endpoints.items():
        operation = api["paths"][path][method]
        assert operation["security"] == [{"BundleValidationBearer": []}]
        parameters = {item["name"]: item for item in operation["parameters"]}
        assert set(parameters) == {
            "X-Runtime-Deployment",
            "X-Runtime-Audience",
            "X-Runtime-Product",
            "X-Runtime-Environment",
            "X-Runtime-Trust-Revision",
        } | ({"X-Runtime-Bundle-Contract"} if method == "post" else set())
        assert all(item["required"] and item["in"] == "header" for item in parameters.values())
        expected = {"200", "400", "401", "403", "405", "429", "503"}
        if method == "post":
            expected |= {"409", "422"}
            request = operation["requestBody"]
            assert request["required"] is True
            assert request["content"]["application/json"]["schema"] == {
                "$ref": "../runtime-bundle-v1/envelope.schema.json"
            }
            assert operation["x-max-body-bytes"] == 262144
        assert set(operation["responses"]) == expected
        assert operation["responses"]["429"]["headers"]["Retry-After"]["schema"] == {"const": "1"}
        for response in operation["responses"].values():
            assert response["headers"]["Cache-Control"]["schema"] == {"const": "no-store"}
    assert "rtbv_" in api["components"]["securitySchemes"]["BundleValidationBearer"]["description"]
    assert api["components"]["schemas"]["ValidationReceipt"]["properties"]["checks"] == {
        "const": {
            "bundle": "passed",
            "assetApproval": "passed",
            "worker": "not_checked",
            "publication": "not_performed",
        }
    }


def test_positive_vector_portable_hashes_and_native_resolution():
    for vector in read("positive-vectors.json"):
        catalog = RuntimeExecutionCatalog.model_validate_json(
            json.dumps(
                {
                    **vector["publicExecutionCatalog"],
                    "baseline_key": "ab" * 32,
                }
            )
        )
        bundle = parse_runtime_bundle(vector["raw"].encode())
        assembly = catalog.resolve(bundle)
        assert assembly.assembly_digest == vector["assemblyDigest"]
        assert bundle.bundle_digest == vector["bundleDigest"]
        assert json_digest(catalog.model_dump(mode="json")) == vector["approvalDigest"]
        assert "baseline_key" not in json.dumps(vector)


def test_negative_vectors_reach_semantic_boundary():
    vector = read("positive-vectors.json")[0]
    catalog = RuntimeExecutionCatalog.model_validate_json(
        json.dumps(
            {
                **vector["publicExecutionCatalog"],
                "baseline_key": "ab" * 32,
            }
        )
    )
    for negative in read("negative-vectors.json"):
        if negative["stage"] == "parse":
            with pytest.raises(ValueError):
                parse_runtime_bundle(negative["raw"].encode())
        else:
            # Recomputed outer hashes must pass syntax/closure before reaching
            # the approval/assembly rejection under test.
            candidate = parse_runtime_bundle(negative["raw"].encode())
            if negative["stage"] == "scope":
                assert candidate.manifest.scope != catalog.scope
            else:
                with pytest.raises(ValueError):
                    catalog.resolve(candidate)
                if negative["stage"] == "assembly":
                    with pytest.raises(ValueError):
                        RuntimeAssembly(bundle=candidate, provider_profile=catalog.providers[0])
