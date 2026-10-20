"""Generic authority protocol through HTTP transport and real RS256 verifier."""

import hashlib
import hmac
import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from zebra_host_grant_broker.app import create_app
from zebra_host_grant_broker.config import BrokerConfigError, BrokerSettings
from zebra_host_grant_broker.current_authority import fetch_authority

from tests.host_grant_broker.test_grant_broker import _key, _settings, _verify_with_zebra


def _body():
    return {
        "audience": "zebra",
        "runId": "fire-1",
        "threadId": "schedule-1",
        "scopes": ["agent.run", "event.read"],
        "resourceRefs": [{"type": "overdoze.invoice", "id": "invoice-42"}],
        "principal": {"userId": "opaque-user-1", "workspaceId": "workspace-1"},
    }


def _rights(settings):
    return {
        "principalId": "opaque-user-1",
        "workspaceId": "workspace-1",
        "hostAppId": settings.host_app_id,
        "namespaceId": settings.namespace_id,
        "scopes": ["agent.run", "event.read", "unused.read"],
        "resourceRefs": [
            {"type": "overdoze.invoice", "id": "invoice-42"},
            {"type": "overdoze.invoice", "id": "invoice-extra"},
        ],
        "expiresAt": (datetime.now(UTC) + timedelta(seconds=90)).isoformat(),
    }


def _headers(body):
    stamp = str(int(time.time()))
    canonical = json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    signature = hmac.new(b"scheduler-secret", f"{stamp}\nnonce\n{digest}".encode(), hashlib.sha256)
    return {
        "X-Zebra-Workload-Identity": "scheduler",
        "X-Zebra-Workload-Timestamp": stamp,
        "X-Zebra-Workload-Nonce": "nonce",
        "X-Zebra-Workload-Signature": signature.hexdigest(),
    }


def _setup(monkeypatch):
    key = _key()
    settings = replace(
        _settings(key),
        authority_mode="generic",
        host_app_id="overdoze",
        namespace_id="overdoze-prod",
        authority_url="https://authority.test/current",
        workload_identities=("scheduler",),
        workload_shared_secret="scheduler-secret",
    )
    rights = _rights(settings)
    seen = []

    def respond(request):
        assert str(request.url) == settings.authority_url
        seen.append(request)
        return httpx.Response(200, json=rights)

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        "zebra_host_grant_broker.app.fetch_authority",
        lambda *args, **kwargs: fetch_authority(*args, **kwargs, transport=transport),
    )
    return key, settings, rights, seen, TestClient(create_app(settings))


def test_signed_current_authority_mints_only_requested_rights(monkeypatch):
    key, settings, rights, seen, client = _setup(monkeypatch)
    body = _body()
    # Even valid signed historical claims are irrelevant to the generic entitlement ceiling.
    body["principal"]["agentScopes"] = None
    body["principal"]["activeSourceIds"] = "irrelevant legacy field"
    headers = _headers(body)
    result = client.post("/exchange", json=body, headers=headers)
    assert result.status_code == 200
    verified = _verify_with_zebra(result.json()["grant"], settings, key)
    assert {ref.key for ref in verified.context.resource_refs} == {
        ("thread", "schedule-1"),
        ("run", "fire-1"),
        ("principal", "opaque-user-1"),
        ("overdoze.invoice", "invoice-42"),
    }
    claims = jwt.decode(
        result.json()["grant"], key.public_key(), algorithms=["RS256"], audience="zebra"
    )
    assert claims["scopes"] == body["scopes"]
    assert claims["exp"] == int(datetime.fromisoformat(rights["expiresAt"]).timestamp())
    assert json.loads(seen[0].content) == body
    for name, value in headers.items():
        assert seen[0].headers[name] == value


def test_signed_request_without_optional_fields_is_forwarded_unchanged(monkeypatch):
    _, _, _, seen, client = _setup(monkeypatch)
    body = _body()
    del body["resourceRefs"]
    result = client.post("/exchange", json=body, headers=_headers(body))
    assert result.status_code == 200
    assert json.loads(seen[0].content) == body
    assert "resourceRefs" not in json.loads(seen[0].content)


def test_valid_hmac_cannot_bypass_current_revocation(monkeypatch):
    _, _, rights, seen, client = _setup(monkeypatch)
    body = _body()
    headers = _headers(body)
    assert client.post("/exchange", json=body, headers=headers).status_code == 200
    rights["scopes"] = []
    denied = client.post("/exchange", json=body, headers=headers)
    assert denied.json() == {"status": "rejected", "reason": "authority_scope_not_allowed"}
    assert len(seen) == 2
    rights["scopes"] = body["scopes"]
    rights["resourceRefs"] = []
    assert (
        client.post("/exchange", json=body, headers=headers).json()["reason"]
        == "authority_resource_not_allowed"
    )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("principalId", "other-user", "authority_identity_mismatch"),
        ("workspaceId", "other-workspace", "authority_identity_mismatch"),
        ("hostAppId", "other-host", "authority_identity_mismatch"),
        ("namespaceId", "other-namespace", "authority_identity_mismatch"),
        ("expiresAt", "2000-01-01T00:00:00+00:00", "authority_expired"),
        ("expiresAt", "2099-01-01T00:00:00", "authority_expired"),
        ("expiresAt", "invalid", "authority_response_invalid"),
        ("scopes", ["agent.run", "agent.run"], "authority_response_invalid"),
        ("resourceRefs", None, "authority_response_invalid"),
    ],
)
def test_authority_drift_or_malformed_rights_fail_closed(monkeypatch, field, value, reason):
    _, _, rights, _, client = _setup(monkeypatch)
    rights[field] = value
    body = _body()
    result = client.post("/exchange", json=body, headers=_headers(body))
    assert result.status_code == 401
    assert result.json() == {"status": "rejected", "reason": reason}


@pytest.mark.parametrize(
    "credential", [{"Authorization": "Bearer opaque-token"}, {"Cookie": "session=opaque"}]
)
def test_interactive_credentials_are_forwarded_to_fixed_authority(monkeypatch, credential):
    _, _, _, seen, client = _setup(monkeypatch)
    body = _body()
    del body["principal"]
    assert client.post("/exchange", json=body, headers=credential).status_code == 200
    for name, value in credential.items():
        assert seen[0].headers[name] == value


def test_tampered_workload_never_reaches_authority(monkeypatch):
    _, _, _, seen, client = _setup(monkeypatch)
    body = _body()
    headers = _headers(body)
    body["principal"]["userId"] = "attacker"
    result = client.post("/exchange", json=body, headers=headers)
    assert result.status_code == 401
    assert result.json()["reason"] == "workload_signature_invalid"
    assert seen == []


@pytest.mark.parametrize(
    "refs",
    [[{"type": kind, "id": "injected"}] for kind in ("thread", "run", "principal")]
    + [[{"type": "x", "id": "1"}] * 2, [{"type": "x", "id": "1"}] * 129],
)
def test_reserved_duplicate_and_unbounded_request_refs_denied(monkeypatch, refs):
    _, _, _, seen, client = _setup(monkeypatch)
    body = {**_body(), "resourceRefs": refs}
    assert client.post("/exchange", json=body, headers=_headers(body)).status_code == 400
    assert seen == []


@pytest.mark.parametrize("network_error", [False, True])
def test_unreachable_authority_never_falls_back_to_legacy(monkeypatch, network_error):
    _, _, _, _, client = _setup(monkeypatch)

    def fail(*args, **kwargs):
        raise AssertionError("legacy must not be called")

    monkeypatch.setattr("zebra_host_grant_broker.app.fetch_viewer", fail)

    def unavailable(request):
        if network_error:
            raise httpx.ConnectError("private credential must never appear")
        return httpx.Response(503)

    transport = httpx.MockTransport(unavailable)
    monkeypatch.setattr(
        "zebra_host_grant_broker.app.fetch_authority",
        lambda *args, **kwargs: fetch_authority(*args, **kwargs, transport=transport),
    )
    body = _body()
    result = client.post("/exchange", json=body, headers=_headers(body))
    assert result.status_code == 401
    assert result.json()["reason"] == (
        "authority_unreachable" if network_error else "authority_rejected"
    )


def _env():
    settings = _settings(_key())
    return {
        "ZEBRA_GRANT_BROKER_" + name: value
        for name, value in {
            "ISSUER": settings.issuer,
            "ORIGIN": settings.origin,
            "PRIVATE_KEY_PEM": settings.private_key_pem,
            "HOST_APP_ID": "other-product",
            "NAMESPACE_ID": "other-prod",
            "AUTHORITY_URL": "https://identity.test/current",
        }.items()
    }


def test_process_defaults_generic_without_trench_configuration():
    settings = BrokerSettings.from_env(_env())
    assert settings.authority_mode == "generic"
    assert settings.allowed_scopes == ("agent.run",)
    assert settings.trench_me_url == settings.trench_sources_url == ""
    assert settings.host_app_id == "other-product"


@pytest.mark.parametrize("missing", ["AUTHORITY_URL", "HOST_APP_ID", "NAMESPACE_ID"])
def test_generic_process_requires_explicit_trust_configuration(missing):
    env = _env()
    del env["ZEBRA_GRANT_BROKER_" + missing]
    with pytest.raises(BrokerConfigError):
        BrokerSettings.from_env(env)


def test_explicit_legacy_process_keeps_trench_defaults():
    env = _env()
    env.update(
        {
            "ZEBRA_GRANT_BROKER_AUTHORITY_MODE": "trench_legacy",
            "ZEBRA_GRANT_BROKER_TRENCH_ME_URL": "https://trench.test/me",
            "ZEBRA_GRANT_BROKER_TRENCH_SOURCES_URL": "https://trench.test/sources",
        }
    )
    del env["ZEBRA_GRANT_BROKER_AUTHORITY_URL"]
    del env["ZEBRA_GRANT_BROKER_HOST_APP_ID"]
    del env["ZEBRA_GRANT_BROKER_NAMESPACE_ID"]
    settings = BrokerSettings.from_env(env)
    assert settings.authority_mode == "trench_legacy"
    assert settings.host_app_id == settings.namespace_id == "trench"


@pytest.mark.parametrize("headers", [{}, {"Cookie": "   "}, {"Authorization": "Bearer "}])
def test_identity_key_and_blank_credentials_do_not_authenticate(monkeypatch, headers):
    _, _, _, seen, client = _setup(monkeypatch)
    result = client.post("/exchange", json=_body(), headers=headers)
    assert result.status_code == 401
    assert seen == []


@pytest.mark.parametrize("raw", ["{", "[]", "null", '"identity-only"'])
def test_malformed_json_is_sanitized(monkeypatch, raw):
    _, _, _, seen, client = _setup(monkeypatch)
    result = client.post("/exchange", content=raw, headers={"Content-Type": "application/json"})
    assert result.status_code == 400
    assert result.json()["reason"] == "request_body_invalid"
    assert seen == []


def test_broker_ttl_remains_upper_bound(monkeypatch):
    _, settings, rights, _, client = _setup(monkeypatch)
    rights["expiresAt"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    body = _body()
    result = client.post("/exchange", json=body, headers=_headers(body))
    assert result.status_code == 200
    claims = jwt.decode(result.json()["grant"], options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == settings.ttl_seconds
