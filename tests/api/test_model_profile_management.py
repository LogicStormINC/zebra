"""Scoped management transport backed by real PostgreSQL."""

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from agent_core.domain.runtime_bundle_json import json_digest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from zebra_agent_api.bundle_management import register_bundle_management
from zebra_agent_api.model_profile_management import (
    CONTRACT,
    PATH,
    register_model_profile_management,
)

from tests.agent_storage.test_postgres_orchestration_admission import dsn as shared_dsn
from tests.api.test_bundle_management import (
    CONTRACT_PATH,
    VALIDATION_PATH,
    configured_fixture,
    write,
)

dsn = shared_dsn


def test_register_replay_and_validate_after_api_recreation(tmp_path, dsn):
    configured, approval_path, approval, bundle, headers = configured_fixture(tmp_path)
    configured = replace(configured, database_url=dsn)
    approval["actions"].extend(["model-profile.register", "model-profile.registration.read"])
    write(approval_path, approval)

    def app():
        application = FastAPI()
        register_model_profile_management(application, configured, "local")
        register_bundle_management(application, configured, "local")
        return application

    path = PATH.format(operationId=uuid4())
    model = bundle["manifest"]["domains"]["model"]["parameters"]
    request = {
        "modelConfigId": str(uuid4()),
        "revision": 1,
        "model": model["model"],
        "approvedProviderProfile": model["provider_profile"],
    }
    catalog = json.loads(Path(configured.runtime_bundle_config).read_text())
    approved = next(
        p for p in catalog["providers"] if p["pin"] == request["approvedProviderProfile"]
    )
    request["expectedConnectionDigest"] = json_digest(
        [approved["base_url"], approved["api_key_env"]]
    )
    write_headers = {**headers, "X-Runtime-Model-Profile-Contract": CONTRACT}
    with TestClient(app()) as client:
        denied = {**write_headers, "X-Runtime-Product": "other"}
        assert client.put(path, headers=denied, json=request).status_code == 403
        assert client.get(path, headers=headers).status_code == 404
        for field in ("base_url", "api_key_env"):
            mismatch = {**approved, field: "different"}
            wrong_digest = json_digest([mismatch["base_url"], mismatch["api_key_env"]])
            wrong_request = {**request, "expectedConnectionDigest": wrong_digest}
            assert client.put(path, headers=write_headers, json=wrong_request).status_code == 409
            assert client.get(path, headers=headers).status_code == 404
        response = client.put(path, headers=write_headers, json=request)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["profilePin"] != model["provider_profile"]
        assert client.put(path, headers=write_headers, json=request).json() == receipt
        conflict = client.put(path, headers=write_headers, json={**request, "revision": 2})
        assert conflict.status_code == 409

    with TestClient(app()) as client:
        assert client.get(path, headers=headers).json() == receipt
        model["provider_profile"] = receipt["profilePin"]
        manifest = bundle["manifest"]
        manifest["lock"] = sorted(
            (
                receipt["profilePin"] if pin == request["approvedProviderProfile"] else pin
                for pin in manifest["lock"]
            ),
            key=lambda pin: (pin["kind"], pin["id"], pin["version"]),
        )
        bundle["bundle_digest"] = json_digest(manifest)
        contract = client.get(CONTRACT_PATH, headers=headers).json()
        validation = client.post(
            VALIDATION_PATH,
            headers={**headers, "X-Runtime-Bundle-Contract": contract["contractDigest"]},
            json=bundle,
        )
        assert validation.status_code == 200, validation.text
        approval["actions"].remove("model-profile.registration.read")
        write(approval_path, approval)
        assert client.get(path, headers=headers).status_code == 403
