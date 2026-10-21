"""Native package checks preserve byte identity without importing uploaded code."""

import base64
import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.script_validation import register_script_validation
from zebra_agent_api.script_validation_contract import (
    CONTRACT_PATH as GET,
)
from zebra_agent_api.script_validation_contract import (
    VALIDATION_PATH as POST,
)
from zebra_agent_api.script_validation_contract import (
    native_script_validation_contract,
)

from tests.api.test_bundle_management import configured_fixture as bundle_fixture
from tests.api.test_bundle_management import write
from tests.test_bundle_assembly import settings

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "rtsv_" + "s" * 43


def configured_fixture(tmp_path):
    active, _, old, _, headers = bundle_fixture(tmp_path)
    approval = {
        **old,
        "schema_version": "cloud-agent.script-validation-approval/1",
        "credential_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
        "actions": ["script.contract.read", "script.validate"],
    }
    path = tmp_path / "script-approval.json"
    write(path, approval)
    request = {
        "schema_version": "cloud-agent.script-validation-request/1",
        "scope": approval["scope"],
        "manifest_base64": base64.b64encode(
            (ROOT / "docs/contracts/native-script-v1/example-manifest.json").read_bytes()
        ).decode(),
        "source_base64": base64.b64encode(
            (ROOT / "docs/contracts/native-script-v1/example.py").read_bytes()
        ).decode(),
    }
    headers = {
        **headers,
        "Authorization": "Bearer " + TOKEN,
        "X-Runtime-Script-Contract": native_script_validation_contract()["contractDigest"],
    }
    return replace(active, script_validation_config=str(path)), path, approval, request, headers


def isolated_app(active):
    app = FastAPI()
    register_script_validation(app, active, "local")
    return app


def test_public_factory_disabled_and_explicit_scoped_composition(tmp_path):
    with TestClient(create_http_app(tmp_path / "off.sqlite", settings=settings())) as client:
        assert client.get(GET, headers={"Authorization": "Bearer " + TOKEN}).status_code == 503
    active, _, approval, request, headers = configured_fixture(tmp_path)
    # No Bundle/catalog approval is needed or implied by pure package validation.
    active = replace(active, runtime_bundle_config=None, bundle_management_config=None)
    with TestClient(create_http_app(tmp_path / "on.sqlite", settings=active)) as client:
        contract = client.get(GET, headers=headers)
        assert contract.status_code == 200, contract.text
        assert contract.json()["contract"] == native_script_validation_contract()
        response = client.post(POST, headers=headers, json=request)
        assert response.status_code == 200, response.text
        assert response.json()["scope"] == approval["scope"]


def test_exact_byte_manifest_and_source_identity_and_no_execution(tmp_path):
    active, _, _, request, headers = configured_fixture(tmp_path)
    sentinel = tmp_path / "MUST_NOT_EXIST"
    source = f"raise RuntimeError('DO_NOT_EXECUTE')\nopen({str(sentinel)!r}, 'w')\n".encode()
    manifest = json.loads(base64.b64decode(request["manifest_base64"]))
    manifest["source_digest"] = "sha256:" + hashlib.sha256(source).hexdigest()
    manifest_raw = json.dumps(manifest, indent=2).encode() + b"\n"
    request.update(
        manifest_base64=base64.b64encode(manifest_raw).decode(),
        source_base64=base64.b64encode(source).decode(),
    )
    raw = json.dumps(request).encode()
    from agent_core.domain.native_script import parse_native_script

    with TestClient(isolated_app(active)) as client:
        response = client.post(
            POST, headers={**headers, "Content-Type": "application/json"}, content=raw
        )
        body = response.json()
        assert response.status_code == 200, body
        assert body["inputDigest"] == "sha256:" + hashlib.sha256(raw).hexdigest()
        assert body["manifestDigest"] == parse_native_script(manifest_raw, source).manifest.digest
        assert body["sourceDigest"] == manifest["source_digest"]
        assert body["sourceBytes"] == len(source)
        assert body["checks"] == dict.fromkeys(
            ["manifest", "sourceDigest", "sourceSyntax"], "passed"
        )
        assert body["capabilities"] == native_script_validation_contract()["capabilities"]
        assert body["capabilities"]["coverageAuthority"] is False
        assert response.headers["cache-control"] == "no-store"
        for secret in (
            TOKEN,
            "DO_NOT_EXECUTE",
            str(sentinel),
            "source_base64",
            "credential_sha256",
        ):
            assert secret not in response.text
        assert not sentinel.exists()
        second = client.post(POST, headers=headers, content=raw + b" ")
        assert second.status_code == 400  # JSON MIME must be explicit.
        second = client.post(
            POST, headers={**headers, "Content-Type": "application/json"}, content=raw + b" "
        )
        assert second.json()["inputDigest"] != body["inputDigest"]
        assert second.json()["manifestDigest"] == body["manifestDigest"]


def test_separate_tokens_scope_actions_and_current_approval(tmp_path):
    active, path, approval, request, headers = configured_fixture(tmp_path)
    with TestClient(isolated_app(active)) as client:
        for prefix in ("rtmg_", "rthm_", "rtpub_", "rtbv_", "operator-", "rtsv_"):
            altered = {**headers, "Authorization": "Bearer " + prefix + "a" * 43}
            assert client.get(GET, headers=altered).status_code == 401
        for field in headers.keys() - {"Authorization", "X-Runtime-Script-Contract"}:
            assert client.get(GET, headers={**headers, field: "other"}).status_code == 403
        for field in request["scope"]:
            value = copy.deepcopy(request)
            value["scope"][field] = (
                "https://other.example" if field == "authority_issuer" else "other"
            )
            assert client.post(POST, headers=headers, json=value).status_code == 403
        assert (
            client.post(
                POST, headers={**headers, "X-Runtime-Script-Contract": "other"}, json=request
            ).status_code
            == 409
        )
        for changes, get_status, post_status in (
            ({"actions": ["script.contract.read"]}, 200, 403),
            ({"actions": ["script.validate"]}, 403, 200),
            ({"expires_at": "2000-01-01T00:00:00Z"}, 403, 403),
            ({"trust_revision": 2}, 403, 403),
            ({"credential_sha256": "0" * 64}, 401, 401),
        ):
            write(path, {**approval, **changes})
            assert client.get(GET, headers=headers).status_code == get_status
            assert client.post(POST, headers=headers, json=request).status_code == post_status
        path.unlink()
        assert client.get(GET, headers=headers).status_code == 503


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "scope_extra",
        "bad_encoding",
        "padding",
        "noncanonical",
        "empty",
        "oversize",
        "duplicate",
        "float",
        "unknown_manifest",
        "effect",
        "syntax",
        "source_digest",
        "utf8",
        "bom",
    ],
)
def test_rejects_without_echo(tmp_path, change):
    active, _, _, request, headers = configured_fixture(tmp_path)
    source = base64.b64decode(request["source_base64"])
    manifest = json.loads(base64.b64decode(request["manifest_base64"]))
    if change == "extra":
        request["unexpected"] = "DO_NOT_ECHO"
    elif change == "scope_extra":
        request["scope"]["extra"] = "DO_NOT_ECHO"
    elif change == "bad_encoding":
        request["source_base64"] = "????"
    elif change == "padding":
        request["source_base64"] += "="
    elif change == "noncanonical":
        # Zg== and Zh== decode to the same byte; only the first is canonical.
        request["source_base64"] = "Zh=="
    elif change == "empty":
        request["source_base64"] = ""
    elif change == "oversize":
        request["source_base64"] = base64.b64encode(b" " * 16385).decode()
    elif change == "float":
        manifest["timeout_seconds"] = 1.0
    elif change == "unknown_manifest":
        manifest["unexpected"] = "DO_NOT_ECHO"
    elif change == "effect":
        manifest["effects"] = "business-write"
    elif change == "source_digest":
        manifest["source_digest"] = "sha256:" + "0" * 64
    elif change in {"syntax", "utf8"}:
        source = b"def DO_NOT_ECHO(" if change == "syntax" else b"\xffDO_NOT_ECHO"
        request["source_base64"] = base64.b64encode(source).decode()
        manifest["source_digest"] = "sha256:" + hashlib.sha256(source).hexdigest()
    if change in {"float", "unknown_manifest", "effect", "source_digest", "syntax", "utf8"}:
        request["manifest_base64"] = base64.b64encode(json.dumps(manifest).encode()).decode()
    raw = json.dumps(request).encode()
    if change == "duplicate":
        raw = raw[:-1] + b',"schema_version":"DO_NOT_ECHO"}'
    if change == "bom":
        raw = b"\xef\xbb\xbf" + raw
    with TestClient(isolated_app(active)) as client:
        response = client.post(
            POST, headers={**headers, "Content-Type": "application/json"}, content=raw
        )
        assert response.status_code == 422, response.text
        assert response.json() == {"error": {"code": "SCRIPT_REJECTED"}}
        assert "DO_NOT_ECHO" not in response.text


def test_framing_rejects_before_native_parser(tmp_path):
    active, _, _, request, headers = configured_fixture(tmp_path)
    with TestClient(isolated_app(active)) as client:
        for path in (GET, POST):
            response = client.request("PROPFIND", path, headers=headers)
            assert response.status_code == 405 and response.headers["allow"] in {"GET", "POST"}
        for extra in (
            {"Cookie": "session=private"},
            {"Content-Encoding": "gzip"},
            {"Content-Length": "0"},
            {"Content-Length": "65537"},
            {"Content-Length": "no"},
            {"Transfer-Encoding": "chunked"},
            {"Content-Type": "text/plain"},
        ):
            assert client.post(POST, headers={**headers, **extra}, json=request).status_code == 400
        assert client.post(POST + "?private=1", headers=headers, json=request).status_code == 400
        for header in ("Authorization", "X-Runtime-Script-Contract", "X-Runtime-Product"):
            pairs = [*headers.items(), (header, headers[header])]
            assert client.post(POST, headers=pairs, json=request).status_code in (400, 401)
        assert client.request("GET", GET, headers=headers, content=b"{}").status_code == 400
        assert client.post(POST, headers=headers, content=b" " * 65537).status_code == 400
