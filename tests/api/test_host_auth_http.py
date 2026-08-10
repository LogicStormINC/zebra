from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from agent_security import HostGrantSecurityError
from agent_storage import sqlite_control_plane_stores
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.http import HostGrantHttpRequest
from zebra_agent_config import ApiSettings, ModelSettings, RuntimeSettings, ZebraAgentSettings


@dataclass
class _FakeHostAuthorizer:
    allowed_origins: tuple[str, ...] = ("https://trench.example.com",)
    calls: list[HostGrantHttpRequest] = field(default_factory=list)

    def authorize(self, request: HostGrantHttpRequest) -> None:
        self.calls.append(request)
        if request.authorization != "Bearer valid-grant":
            raise HostGrantSecurityError("grant rejected")
        if request.path.endswith("/scope-denied"):
            raise HostGrantSecurityError("scope rejected")


def _local_settings(*, auth_token: str | None = None) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=auth_token),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )


def _cloud_settings(database_url: str) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="cloud",
        database_url=database_url,
        api=ApiSettings(auth_token="must-not-be-used-as-cloud-fallback"),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        runtime=RuntimeSettings(
            runtime_class="gvisor",
            image="registry.example/zebra@sha256:" + "a" * 64,
            require_workspace_quota=True,
        ),
    )


def _cloud_client(tmp_path: Path, authorizer: _FakeHostAuthorizer | None) -> TestClient:
    database_path = tmp_path / "sessions.sqlite"
    stores = sqlite_control_plane_stores(database_path)
    return TestClient(
        create_http_app(
            database_path,
            settings=_cloud_settings("postgresql://zebra@example/zebra"),
            stores=stores,
            host_grant_authorizer=authorizer,
        )
    )


def test_local_bearer_compatibility_and_health_remain_unchanged(tmp_path: Path) -> None:
    client = TestClient(
        create_http_app(tmp_path / "sessions.sqlite", settings=_local_settings(auth_token="secret"))
    )

    assert client.get("/health").status_code == 200
    response = client.get("/sessions/not-a-valid-uuid")
    assert response.status_code == 401
    assert response.json()["reason"] == "missing_or_invalid_bearer_token"
    cors = client.get("/health", headers={"Origin": "https://any-local-origin.example"})
    assert cors.headers["access-control-allow-origin"] == "*"


def test_cloud_missing_grant_and_authorizer_fail_closed_before_route(tmp_path: Path) -> None:
    authorizer = _FakeHostAuthorizer()
    client = _cloud_client(tmp_path, authorizer)

    missing = client.get("/sessions/not-a-valid-uuid")
    assert missing.status_code == 401
    assert missing.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_host_grant",
    }
    assert authorizer.calls == []

    unconfigured = _cloud_client(tmp_path / "unconfigured", None)
    response = unconfigured.get(
        "/sessions/not-a-valid-uuid",
        headers={"Authorization": "Bearer looks-like-a-grant"},
    )
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "reason": "host_grant_authorizer_unconfigured",
    }


def test_cloud_origin_and_scope_are_rejected_before_business_handler(tmp_path: Path) -> None:
    authorizer = _FakeHostAuthorizer()
    client = _cloud_client(tmp_path, authorizer)

    wrong_origin = client.get(
        "/sessions/not-a-valid-uuid",
        headers={
            "Authorization": "Bearer valid-grant",
            "Origin": "https://evil.example.com",
        },
    )
    assert wrong_origin.status_code == 403
    assert wrong_origin.json()["reason"] == "host_origin_not_allowed"
    assert authorizer.calls == []

    wrong_scope = client.get(
        "/sessions/scope-denied",
        headers={
            "Authorization": "Bearer valid-grant",
            "Origin": "https://trench.example.com",
        },
    )
    assert wrong_scope.status_code == 403
    assert wrong_scope.json() == {
        "status": "forbidden",
        "reason": "host_grant_rejected",
    }
    assert len(authorizer.calls) == 1


def test_cloud_cors_uses_exact_authorizer_origins_without_reflection(tmp_path: Path) -> None:
    client = _cloud_client(tmp_path, _FakeHostAuthorizer())

    allowed = client.options(
        "/sessions/not-a-valid-uuid",
        headers={
            "Origin": "https://trench.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert allowed.status_code in {200, 204}
    assert allowed.headers["access-control-allow-origin"] == "https://trench.example.com"

    rejected = client.options(
        "/sessions/not-a-valid-uuid",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert rejected.status_code >= 400
    assert "access-control-allow-origin" not in rejected.headers


def test_cloud_authorizer_origin_configuration_is_normalized_and_wildcards_fail(
    tmp_path: Path,
) -> None:
    authorizer = _FakeHostAuthorizer(allowed_origins=("https://Trench.Example.com/",))
    client = _cloud_client(tmp_path, authorizer)
    response = client.get(
        "/sessions/not-a-valid-uuid",
        headers={
            "Authorization": "Bearer valid-grant",
            "Origin": "https://trench.example.com",
        },
    )
    assert response.status_code == 400
    with pytest.raises(ValueError, match="exact HTTPS origins"):
        _cloud_client(tmp_path / "wildcard", _FakeHostAuthorizer(allowed_origins=("*",)))
