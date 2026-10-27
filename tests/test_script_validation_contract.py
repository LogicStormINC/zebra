"""Producer exports, native vectors and unchanged A/P2 schema artifacts."""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from zebra_agent_api.script_validation_contract import (
    CONTRACT_PATH as GET,
)
from zebra_agent_api.script_validation_contract import (
    VALIDATION_PATH as POST,
)
from zebra_agent_api.script_validation_contract import (
    ScriptValidationRequest,
    native_script_validation_contract,
)

from tests.api.test_script_validation import configured_fixture, isolated_app

ROOT = Path("docs/contracts/script-validation-v1")


def test_export_is_current_and_all_vectors_use_real_adapter(tmp_path):
    assert json.loads((ROOT / "contract.json").read_bytes()) == native_script_validation_contract()
    schema = json.loads((ROOT / "request.schema.json").read_bytes())
    assert schema == ScriptValidationRequest.model_json_schema()
    response_schema = json.loads((ROOT / "response.schema.json").read_bytes())
    active, _, approval, _, headers = configured_fixture(tmp_path)
    with TestClient(isolated_app(active)) as client:
        assert client.get(GET, headers=headers).json()["contract"] == json.loads(
            (ROOT / "contract.json").read_bytes()
        )
        for vector in json.loads((ROOT / "positive-vectors.json").read_bytes()):
            assert json.loads(vector["raw"])["scope"] == approval["scope"]
            response = client.post(
                POST,
                headers={**headers, "Content-Type": "application/json"},
                content=vector["raw"].encode(),
            )
            assert response.status_code == 200, response.text
            for field in ("inputDigest", "manifestDigest", "sourceDigest"):
                assert response.json()[field] == vector[field]
            assert set(response.json()) == set(response_schema["required"])
            for field, specification in response_schema["properties"].items():
                if "const" in specification:
                    assert response.json()[field] == specification["const"]
        for vector in json.loads((ROOT / "negative-vectors.json").read_bytes()):
            response = client.post(
                POST,
                headers={**headers, "Content-Type": "application/json"},
                content=vector["raw"].encode(),
            )
            assert response.status_code == vector["status"], vector["name"]


def test_current_contract_identity_and_no_implicit_worker_approval():
    from agent_core.domain.runtime_bundle_json import json_digest

    document = native_script_validation_contract()
    assert document.pop("contractDigest") == json_digest(document)
    assert document["capabilities"]["assetApproval"] == "not_performed"
    assert document["capabilities"]["coverageAuthority"] is False
    assert document["transport"]["maxRequestBytes"] == 65536
    openapi = json.loads((ROOT / "openapi.json").read_bytes())
    assert set(openapi["paths"]) == {GET, POST}
    headers = openapi["paths"][POST]["post"]["parameters"]
    assert headers[-1]["schema"]["const"] == native_script_validation_contract()["contractDigest"]


@pytest.mark.parametrize(
    "directory",
    [
        "native-script-v1",
        "native-script-worker-v1",
        "runtime-bundle-v1",
        "bundle-validation-v1",
        "runtime-publication-v1",
    ],
)
def test_old_producer_artifacts_are_byte_identical(directory):
    root = Path("docs/contracts") / directory
    digest = hashlib.sha256()
    paths = sorted(path for path in root.rglob("*") if path.is_file())
    assert paths
    for path in paths:
        digest.update(
            path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0"
        )
    expected = json.loads((ROOT / "prior-artifacts.json").read_bytes())
    assert "sha256:" + digest.hexdigest() == expected["directoryDigests"][directory]
