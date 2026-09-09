"""Login authority is a Host-declared ceiling, not an operator-wide permission."""

import hashlib
import hmac
import json
from dataclasses import replace

import httpx
import pytest
from zebra_host_grant_broker.config import DEFAULT_ALLOWED_SCOPES, BrokerSettings
from zebra_host_grant_broker.grant_minting import ExchangeRequest, GrantMintError
from zebra_host_grant_broker.trench_session import TrenchSessionError, TrenchViewer, fetch_viewer
from zebra_host_grant_broker.workload_auth import WorkloadAuthError, verify_workload

from tests.host_grant_broker.test_grant_broker import _key, _settings


def _viewer(extra: dict[str, object]) -> TrenchViewer:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["cookie"] == "session=test"
        data = (
            {"viewer": {"user_id": "u", "workspace_id": "w", **extra}}
            if request.url.path == "/me"
            else {"items": []}
        )
        return httpx.Response(200, json={"data": data})

    return fetch_viewer(
        "https://trench.test/me",
        "https://trench.test/sources",
        "session=test",
        timeout_seconds=1,
        transport=httpx.MockTransport(respond),
    )


def _request(*scopes: str) -> ExchangeRequest:
    return ExchangeRequest("zebra", "thread", "run", scopes)


def test_declared_login_ceiling_and_operator_ceiling() -> None:
    viewer = _viewer({"agent_scopes": ["agent.run", "extensions.read", "extensions.manage"]})
    _request("extensions.manage").authorize(viewer)
    assert {"extensions.read", "extensions.manage"}.issubset(DEFAULT_ALLOWED_SCOPES)
    with pytest.raises(GrantMintError, match="scope_not_allowed"):
        _request("extensions.manage").enforce(_settings(_key()))
    with pytest.raises(GrantMintError, match="viewer_scope_not_allowed"):
        _request("subscription.write").authorize(viewer)


@pytest.mark.parametrize("scope", ["extensions.read", "extensions.manage"])
def test_legacy_viewer_preserves_base_but_denies_extensions(scope: str) -> None:
    viewer = _viewer({})
    assert viewer.allowed_scopes is None
    _request("agent.run").authorize(viewer)
    with pytest.raises(GrantMintError, match="viewer_scope_not_allowed"):
        _request(scope).authorize(viewer)


def test_empty_ceiling_denies_every_scope() -> None:
    viewer = _viewer({"agent_scopes": []})
    with pytest.raises(GrantMintError, match="viewer_scope_not_allowed"):
        _request("agent.run").authorize(viewer)


INVALID = [
    None,
    "extensions.manage",
    {},
    [1],
    [""],
    [" x"],
    ["x", "x"],
    ["x" * 513],
    [str(i) for i in range(65)],
]


@pytest.mark.parametrize("scopes", INVALID)
def test_malformed_viewer_ceiling_rejected(scopes: object) -> None:
    with pytest.raises(TrenchSessionError, match="viewer_agent_scopes_invalid"):
        _viewer({"agent_scopes": scopes})


def _signature(body: dict[str, object]) -> str:
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    signed = f"100\nnonce\n{hashlib.sha256(raw).hexdigest()}".encode()
    return hmac.new(b"test-secret", signed, hashlib.sha256).hexdigest()


def _verify(settings: BrokerSettings, body: dict[str, object], signature: str | None = None):
    return verify_workload(
        settings,
        body,
        identity="worker",
        timestamp="100",
        nonce="nonce",
        signature=signature or _signature(body),
        now=100,
    )


@pytest.fixture
def workload_settings() -> BrokerSettings:
    return replace(
        _settings(_key()), workload_identities=("worker",), workload_shared_secret="test-secret"
    )


def test_signed_workload_ceiling_cannot_be_expanded(workload_settings: BrokerSettings) -> None:
    principal = {"userId": "u", "workspaceId": "w", "agentScopes": ["extensions.read"]}
    body: dict[str, object] = {"principal": principal}
    signature = _signature(body)
    viewer = _verify(workload_settings, body).viewer
    _request("extensions.read").authorize(viewer)
    with pytest.raises(GrantMintError, match="viewer_scope_not_allowed"):
        _request("extensions.manage").authorize(viewer)
    principal["agentScopes"] = ["extensions.read", "extensions.manage"]
    with pytest.raises(WorkloadAuthError, match="workload_signature_invalid"):
        _verify(workload_settings, body, signature)


@pytest.mark.parametrize("scopes", INVALID)
def test_malformed_signed_workload_ceiling_rejected(
    workload_settings: BrokerSettings, scopes: object
) -> None:
    body = {"principal": {"userId": "u", "workspaceId": "w", "agentScopes": scopes}}
    with pytest.raises(WorkloadAuthError, match="workload_agent_scopes_invalid"):
        _verify(workload_settings, body)


def test_legacy_workload_does_not_gain_management(workload_settings: BrokerSettings) -> None:
    viewer = _verify(workload_settings, {"principal": {"userId": "u", "workspaceId": "w"}}).viewer
    _request("agent.run").authorize(viewer)
    with pytest.raises(GrantMintError, match="viewer_scope_not_allowed"):
        _request("extensions.manage").authorize(viewer)
