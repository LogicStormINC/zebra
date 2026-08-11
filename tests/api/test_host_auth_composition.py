from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from zebra_agent_api import create_http_app
from zebra_agent_config import ApiSettings, ModelSettings, RuntimeSettings, ZebraAgentSettings


class _FakePostgresStores:
    deployment_namespace = "deployment-a"


class _Authorizer:
    allowed_origins = ("https://trench.example.com",)


def _settings(database_url: str) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="cloud",
        database_url=database_url,
        api=ApiSettings(auth_token="must-not-be-used"),
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


def test_cloud_http_factory_composes_default_postgres_host_authorizer(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    import importlib

    http_module = importlib.import_module("zebra_agent_api.http")
    host_auth_module = importlib.import_module("zebra_agent_api.host_auth")
    calls: list[tuple[str, str]] = []
    authorizer = _Authorizer()

    def build(database_url: str, *, deployment_namespace: str) -> _Authorizer:
        calls.append((database_url, deployment_namespace))
        return authorizer

    monkeypatch.setattr(http_module, "PostgresControlPlaneStores", _FakePostgresStores)
    monkeypatch.setattr(host_auth_module, "build_postgres_host_grant_authorizer", build)

    app = create_http_app(
        tmp_path / "api.sqlite",
        settings=_settings("postgresql://zebra@example/zebra"),
        stores=_FakePostgresStores(),  # type: ignore[arg-type]
    )

    assert calls == [("postgresql://zebra@example/zebra", "deployment-a")]
    assert app is not None


def test_cloud_http_factory_keeps_explicit_authorizer(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    import importlib

    http_module = importlib.import_module("zebra_agent_api.http")
    host_auth_module = importlib.import_module("zebra_agent_api.host_auth")
    monkeypatch.setattr(
        http_module,
        "PostgresControlPlaneStores",
        _FakePostgresStores,
    )
    monkeypatch.setattr(
        host_auth_module,
        "build_postgres_host_grant_authorizer",
        _unexpected_composition,
    )
    explicit = _Authorizer()

    app = create_http_app(
        tmp_path / "api.sqlite",
        settings=_settings("postgresql://zebra@example/zebra"),
        stores=_FakePostgresStores(),  # type: ignore[arg-type]
        host_grant_authorizer=explicit,  # type: ignore[arg-type]
    )

    response = TestClient(app).options(
        "/sessions",
        headers={"Origin": "https://trench.example.com"},
    )
    assert response.status_code == 200


def _unexpected_composition(*args: object, **kwargs: object) -> None:
    raise AssertionError("unexpected composition")
