"""Host Grant broker contract tests.

The minted grant is verified through the real Zebra verifier stack
(`agent_security` decoder + verifier) to prove broker/verifier agreement,
including the `extra="forbid"` claim boundary and single-use consumption
semantics.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import replace
from datetime import UTC, datetime

import jwt as pyjwt
import pytest
from agent_security.host_grant import HostGrantVerificationConfig, HostGrantVerifier, JwtAlgorithm
from agent_security.jwt_adapter import PyJwtHostGrantDecoder
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from zebra_host_grant_broker.app import create_app
from zebra_host_grant_broker.config import BrokerSettings
from zebra_host_grant_broker.grant_minting import ExchangeRequest, GrantMintError, mint_grant
from zebra_host_grant_broker.keys import jwk_document
from zebra_host_grant_broker.trench_session import TrenchSessionError, TrenchViewer, fetch_viewer


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _settings(key) -> BrokerSettings:
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return BrokerSettings(
        issuer="https://broker.local",
        audience="zebra",
        host_app_id="trench",
        namespace_id="trench-prod",
        workspace_ref="trench-default",
        origin="https://trench.local",
        policy_version="trench-read-v1",
        allowed_scopes=(
            "agent.run",
            "event.read",
            "evidence.read",
            "entity.read",
            "topic.read",
            "source.read",
            "history.read",
        ),
        private_key_pem=pem,
        key_id="test-key-1",
        ttl_seconds=300,
        trench_me_url="https://trench.local/api/trench-ai/me",
        trench_sources_url="https://trench.local/api/trench-ai/sources",
        trench_timeout_seconds=5,
        max_runtime_seconds=1800,
        max_model_tokens=1_000_000,
        max_artifact_bytes=64_000_000,
    )


class _StaticJwks:
    def __init__(self, key, key_id: str) -> None:
        self.document = jwk_document(key, key_id)

    def resolve(self, jwks_uri: str, token: str):
        return pyjwt.PyJWK.from_dict({"alg": "RS256", **self.document}).key


def _verify_with_zebra(token: str, settings: BrokerSettings, key):
    config = HostGrantVerificationConfig(
        issuer=settings.issuer,
        audience=settings.audience,
        jwks_uri="https://broker.local/.well-known/jwks.json",
        allowed_origins=(settings.origin,),
        algorithms=frozenset({JwtAlgorithm.RS256}),
    )
    decoded = PyJwtHostGrantDecoder(_StaticJwks(key, settings.key_id)).decode(token, config=config)
    verified = HostGrantVerifier(config).verify(
        decoded.grant,
        algorithm=decoded.algorithm,
        now=datetime.now(UTC),
        expected_host_app_id=settings.host_app_id,
        required_scopes=("agent.run", "event.read"),
    )
    return verified


def test_minted_grant_passes_real_zebra_verifier():
    key = _key()
    settings = _settings(key)
    request = ExchangeRequest(
        audience="zebra",
        thread_id="0f0e8b74-8d64-4d55-9f8e-2a1b3c4d5e6f",
        run_id="run-123",
        scopes=("agent.run", "event.read", "topic.read"),
    )
    viewer = TrenchViewer(user_id="user-42", workspace_id="ws-7")
    token = mint_grant(settings, key, request, viewer)

    assert "\n" not in token and len(token.encode()) <= 8 * 1024
    verified = _verify_with_zebra(token, settings, key)
    assert verified.context.host_app_id == "trench"
    assert verified.context.namespace_id == "trench-prod"
    verified.context.require_scope("topic.read")
    resources = {ref.key for ref in verified.context.resource_refs}
    assert ("thread", "0f0e8b74-8d64-4d55-9f8e-2a1b3c4d5e6f") in resources
    assert ("run", "run-123") in resources
    assert ("principal", "user-42") in resources


def test_grant_carries_exactly_the_model_claim_set():
    key = _key()
    settings = _settings(key)
    request = ExchangeRequest(
        audience="zebra", thread_id="t-1", run_id="r-1", scopes=("agent.run",)
    )
    token = mint_grant(settings, key, request, TrenchViewer("u", ""))
    claims = pyjwt.decode(
        token,
        key=key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
        algorithms=["RS256"],
        audience="zebra",
        issuer="https://broker.local",
    )
    assert set(claims) == {
        "iss",
        "aud",
        "sub",
        "jti",
        "iat",
        "nbf",
        "exp",
        "host_app_id",
        "namespace_id",
        "workspace_ref",
        "resource_refs",
        "scopes",
        "limits",
        "origin",
        "policy_version",
    }
    assert claims["workspace_ref"] == "trench-default"
    assert claims["resource_refs"] == [
        {"type": "thread", "id": "t-1"},
        {"type": "run", "id": "r-1"},
        {"type": "principal", "id": "u"},
    ]


def test_exchange_rejects_unknown_scope_and_audience():
    settings = _settings(_key())
    with pytest.raises(GrantMintError):
        ExchangeRequest(
            audience="other", thread_id="t", run_id="r", scopes=("agent.run",)
        ).enforce(settings)
    with pytest.raises(GrantMintError):
        ExchangeRequest(
            audience="zebra", thread_id="t", run_id="r", scopes=("bank.write",)
        ).enforce(settings)


def test_fetch_viewer_extracts_identity():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Cookie"] == "trench_ai_product_session=abc"
        if request.url.path.endswith("/sources"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "items": [
                            {
                                "source_id": "src-active",
                                "subscription_status": "active",
                            },
                            {
                                "source_id": "src-paused",
                                "subscription_status": "paused",
                            },
                        ]
                    },
                },
            )
        return httpx.Response(
            200,
            json={"success": True, "data": {"viewer": {"user_id": "u9", "workspace_id": "w1"}}},
        )

    viewer = fetch_viewer(
        "https://trench.local/api/trench-ai/me",
        "https://trench.local/api/trench-ai/sources",
        "trench_ai_product_session=abc",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )
    assert viewer == TrenchViewer(
        user_id="u9",
        workspace_id="w1",
        active_source_ids=frozenset({"src-active"}),
    )


def test_fetch_viewer_rejects_inactive_session():
    import httpx

    transport = httpx.MockTransport(lambda request: httpx.Response(401))
    with pytest.raises(TrenchSessionError) as excinfo:
        fetch_viewer(
            "https://x.local/me",
            "https://x.local/sources",
            "c=1",
            timeout_seconds=5,
            transport=transport,
        )
    assert str(excinfo.value) == "session_inactive"


def _client(settings: BrokerSettings, viewer: TrenchViewer | None) -> TestClient:
    import zebra_host_grant_broker.app as app_module

    if viewer is None:
        def fail(*args, **kwargs):
            raise TrenchSessionError("session_inactive")

        app_module.fetch_viewer = fail
    else:
        app_module.fetch_viewer = lambda *args, **kwargs: viewer
    return TestClient(create_app(settings))


def test_exchange_endpoint_mints_grant():
    key = _key()
    settings = _settings(key)
    client = _client(settings, TrenchViewer("user-42", "ws-7"))
    response = client.post(
        "/exchange",
        json={
            "audience": "zebra",
            "runId": "run-1",
            "scopes": ["agent.run", "event.read"],
            "threadId": "0f0e8b74-8d64-4d55-9f8e-2a1b3c4d5e6f",
        },
        headers={"Cookie": "trench_ai_product_session=abc"},
    )
    assert response.status_code == 200
    token = response.json()["grant"]
    _verify_with_zebra(token, settings, key)


def test_workload_exchange_mints_principal_bound_grant_without_cookie():
    key = _key()
    settings = _settings(key)
    settings = replace(
        settings,
        workload_identities=("trench-agent-worker",),
        workload_shared_secret="server-secret",
    )
    client = TestClient(create_app(settings))
    body = {
        "audience": "zebra",
        "runId": "run-server-1",
        "scopes": ["agent.run", "event.read", "source.read", "history.read"],
        "threadId": "0f0e8b74-8d64-4d55-9f8e-2a1b3c4d5e6f",
        "resourceRefs": [
            {"type": "trench.source", "id": "src-1"},
            {"type": "trench.history", "id": "user-42"},
        ],
        "principal": {
            "activeSourceIds": ["src-1"],
            "userId": "user-42",
            "workspaceId": "ws-7",
        },
    }
    timestamp = str(int(time.time()))
    nonce = "turn-1-grant-1"
    digest = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    signature = hmac.new(
        b"server-secret", f"{timestamp}\n{nonce}\n{digest}".encode(), hashlib.sha256
    ).hexdigest()

    headers = {
        "X-Zebra-Workload-Identity": "trench-agent-worker",
        "X-Zebra-Workload-Timestamp": timestamp,
        "X-Zebra-Workload-Nonce": nonce,
        "X-Zebra-Workload-Signature": signature,
    }
    response = client.post(
        "/exchange",
        json=body,
        headers=headers,
    )

    assert response.status_code == 200
    verified = _verify_with_zebra(response.json()["grant"], settings, key)
    assert ("principal", "user-42") in {ref.key for ref in verified.context.resource_refs}
    repeated = client.post("/exchange", json=body, headers=headers)
    assert repeated.status_code == 200
    first_jti = pyjwt.decode(
        response.json()["grant"], options={"verify_signature": False}
    )["jti"]
    repeated_jti = pyjwt.decode(
        repeated.json()["grant"], options={"verify_signature": False}
    )["jti"]
    assert repeated_jti == first_jti


def test_workload_exchange_rejects_tampered_principal():
    key = _key()
    settings = _settings(key)
    settings = replace(
        settings,
        workload_identities=("trench-agent-worker",),
        workload_shared_secret="server-secret",
    )
    client = TestClient(create_app(settings))
    body = {
        "audience": "zebra",
        "runId": "run-server-1",
        "scopes": ["agent.run"],
        "threadId": "thread-1",
        "principal": {"activeSourceIds": [], "userId": "attacker", "workspaceId": "ws-7"},
    }
    response = client.post(
        "/exchange",
        json=body,
        headers={
            "X-Zebra-Workload-Identity": "trench-agent-worker",
            "X-Zebra-Workload-Timestamp": str(int(time.time())),
            "X-Zebra-Workload-Nonce": "turn-1-grant-1",
            "X-Zebra-Workload-Signature": "0" * 64,
        },
    )

    assert response.status_code == 401
    assert response.json()["reason"] == "workload_signature_invalid"


def test_exchange_mints_only_viewer_authorized_read_resources():
    key = _key()
    settings = _settings(key)
    client = _client(
        settings,
        TrenchViewer("user-42", "ws-7", frozenset({"src-1"})),
    )
    response = client.post(
        "/exchange",
        json={
            "audience": "zebra",
            "runId": "run-1",
            "scopes": [
                "agent.run",
                "event.read",
                "topic.read",
                "source.read",
                "history.read",
            ],
            "threadId": "thread-1",
            "resourceRefs": [
                {"type": "trench.source", "id": "src-1"},
                {"type": "trench.topic", "id": "robotics"},
                {"type": "trench.history", "id": "user-42"},
            ],
        },
        headers={"Cookie": "trench_ai_product_session=abc"},
    )

    assert response.status_code == 200
    verified = _verify_with_zebra(response.json()["grant"], settings, key)
    assert {ref.key for ref in verified.context.resource_refs} >= {
        ("trench.source", "src-1"),
        ("trench.topic", "robotics"),
        ("trench.history", "user-42"),
    }


def test_exchange_rejects_unsubscribed_source_and_unbound_business_resource():
    settings = _settings(_key())
    client = _client(
        settings,
        TrenchViewer("user-42", "ws-7", frozenset({"src-1"})),
    )
    base = {
        "audience": "zebra",
        "runId": "run-1",
        "scopes": ["agent.run", "event.read", "topic.read"],
        "threadId": "thread-1",
    }
    headers = {"Cookie": "trench_ai_product_session=abc"}

    unsubscribed = client.post(
        "/exchange",
        json={**base, "resourceRefs": [{"type": "trench.source", "id": "src-2"}]},
        headers=headers,
    )
    no_source = client.post(
        "/exchange",
        json={**base, "resourceRefs": [{"type": "trench.topic", "id": "robotics"}]},
        headers=headers,
    )

    assert unsubscribed.json() == {"status": "rejected", "reason": "source_not_allowed"}
    assert no_source.json() == {"status": "rejected", "reason": "source_binding_required"}


def test_exchange_rejects_another_users_history_ledger():
    settings = _settings(_key())
    client = _client(
        settings,
        TrenchViewer("user-42", "ws-7"),
    )
    response = client.post(
        "/exchange",
        json={
            "audience": "zebra",
            "runId": "run-1",
            "scopes": ["agent.run", "history.read"],
            "threadId": "thread-1",
            "resourceRefs": [
                {"type": "trench.history", "id": "user-other"}
            ],
        },
        headers={"Cookie": "trench_ai_product_session=abc"},
    )

    assert response.json() == {
        "status": "rejected",
        "reason": "history_not_allowed",
    }


def test_exchange_endpoint_rejections():
    settings = _settings(_key())
    client = _client(settings, None)
    no_cookie = client.post(
        "/exchange",
        json={"audience": "zebra", "runId": "r", "scopes": ["agent.run"], "threadId": "t"},
    )
    assert no_cookie.status_code == 401
    inactive = client.post(
        "/exchange",
        json={"audience": "zebra", "runId": "r", "scopes": ["agent.run"], "threadId": "t"},
        headers={"Cookie": "trench_ai_product_session=stale"},
    )
    assert inactive.status_code == 401
    bad_scope = client.post(
        "/exchange",
        json={"audience": "zebra", "runId": "r", "scopes": ["nope.write"], "threadId": "t"},
        headers={"Cookie": "c=1"},
    )
    assert bad_scope.status_code == 400


def test_jwks_endpoint_publishes_signing_key():
    key = _key()
    settings = _settings(key)
    client = TestClient(create_app(settings))
    document = client.get("/.well-known/jwks.json").json()["keys"][0]
    assert document["kty"] == "RSA" and document["alg"] == "RS256"
    assert document["kid"] == settings.key_id
