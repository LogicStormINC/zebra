"""Explicit Task-control exchange must never silently widen a normal Run grant."""

from datetime import UTC, datetime

import pytest
from agent_security.host_grant import HostGrantVerificationConfig, HostGrantVerifier, JwtAlgorithm
from agent_security.jwt_adapter import PyJwtHostGrantDecoder
from zebra_host_grant_broker.grant_minting import ExchangeRequest, GrantMintError, mint_grant
from zebra_host_grant_broker.trench_session import TrenchViewer

from tests.host_grant_broker.test_grant_broker import _key, _settings, _StaticJwks


def body(**changes):
    return {
        "audience": "zebra",
        "threadId": "owned-thread",
        "scopes": ["agent.run"],
        "taskControl": True,
        **changes,
    }


def test_explicit_task_control_grant_round_trips_through_real_verifier():
    key = _key()
    settings = _settings(key)
    request = ExchangeRequest.parse(body())
    request.enforce(settings)
    viewer = TrenchViewer(user_id="owner", workspace_id="workspace", active_source_ids=frozenset())
    request.authorize(viewer)
    config = HostGrantVerificationConfig(
        issuer=settings.issuer,
        audience=settings.audience,
        jwks_uri="https://broker.local/.well-known/jwks.json",
        allowed_origins=(settings.origin,),
        algorithms=frozenset({JwtAlgorithm.RS256}),
    )
    token = mint_grant(settings, key, request, viewer)
    decoded = PyJwtHostGrantDecoder(_StaticJwks(key, settings.key_id)).decode(token, config=config)
    verified = HostGrantVerifier(config).verify(
        decoded.grant,
        algorithm=decoded.algorithm,
        now=datetime.now(UTC),
        expected_host_app_id=settings.host_app_id,
        required_scopes=("agent.run",),
    )
    assert {ref.resource_type for ref in verified.context.resource_refs} == {"thread", "principal"}
    assert set(verified.context.scopes) == {"agent.run"}


@pytest.mark.parametrize(
    "changes",
    [
        {"taskControl": False},
        {"taskControl": "true"},
        {"taskControl": 1},
        {"runId": "run-one"},
        {"scopes": ["agent.run", "source.read"]},
        {"resourceRefs": [{"type": "trench.source", "id": "source"}]},
    ],
)
def test_task_control_rejects_implicit_or_mixed_authority(changes):
    with pytest.raises(GrantMintError):
        ExchangeRequest.parse(body(**changes))


def test_normal_exchange_still_requires_and_retains_run_binding():
    request = ExchangeRequest.parse(body(taskControl=False, runId="run-one"))
    assert request.run_id == "run-one"


@pytest.mark.parametrize("mode", ["cookie", "workload"])
def test_task_control_http_entry_keeps_exact_signed_body(mode):
    import hashlib
    import hmac
    import json
    import time
    from dataclasses import replace

    from fastapi.testclient import TestClient
    from zebra_host_grant_broker.app import create_app

    from tests.host_grant_broker.test_grant_broker import _client

    key = _key()
    settings = replace(
        _settings(key), workload_identities=("worker",), workload_shared_secret="fixture-key"
    )
    payload = body(resourceRefs=[])
    if mode == "cookie":
        client = _client(settings, TrenchViewer("owner", "workspace"))
        headers = {"Cookie": "fixture=session"}
    else:
        client = TestClient(create_app(settings))
        payload["principal"] = {
            "userId": "owner",
            "workspaceId": "workspace",
            "activeSourceIds": [],
            "agentScopes": ["agent.run"],
        }
        stamp, nonce = str(int(time.time())), "fixture-nonce"
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        signature = hmac.new(
            b"fixture-key", f"{stamp}\n{nonce}\n{digest}".encode(), hashlib.sha256
        ).hexdigest()
        headers = {
            "X-Zebra-Workload-Identity": "worker",
            "X-Zebra-Workload-Timestamp": stamp,
            "X-Zebra-Workload-Nonce": nonce,
            "X-Zebra-Workload-Signature": signature,
        }
    response = client.post("/exchange", json=payload, headers=headers)
    assert response.status_code == 200, response.json()
    import jwt

    claims = jwt.decode(
        response.json()["grant"], key.public_key(), algorithms=["RS256"], audience="zebra"
    )
    assert claims["scopes"] == ["agent.run"]
    assert not any(ref["type"] == "run" for ref in claims["resource_refs"])
