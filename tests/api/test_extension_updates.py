import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from agent_core.ports.extensions import (
    ExtensionRevisionConflictError,
    ExtensionSkillConflictError,
    ExtensionStore,
)
from agent_storage import sqlite_control_plane_stores
from fastapi.testclient import TestClient
from starlette.requests import Request
from zebra_agent_api import create_http_app
from zebra_agent_api.extension_reads import extension_read_response
from zebra_agent_config import load_settings

from tests.agent_security.test_extension_authority import _verified
from tests.api.test_extension_reads import AUTH, MCP, PREFIX, SKILL, Authorizer
from tests.api.test_host_auth_http import _cloud_settings, _local_settings


def _client(
    tmp_path: Path,
    store: AsyncMock,
    *,
    scopes: list[str] | None = None,
    enabled: bool = True,
    local: bool = False,
) -> TestClient:
    database = tmp_path / "updates.sqlite"
    settings = _local_settings() if local else _cloud_settings("postgresql://unused/zebra")
    return TestClient(
        create_http_app(
            database,
            settings=replace(settings, cloud_extensions_manage_enabled=enabled),
            stores=sqlite_control_plane_stores(database),
            extension_store=store,
            host_grant_authorizer=Authorizer(
                _verified(
                    scopes=scopes if scopes is not None else ["extensions.manage"],
                )
            ),
        )
    )


@pytest.fixture
def store() -> AsyncMock:
    result = AsyncMock(spec=ExtensionStore)
    result.get_skill.return_value = SKILL
    result.get_mcp.return_value = MCP
    return result


@pytest.mark.parametrize(
    "collection,identifier",
    [
        ("skill-installations", SKILL.installation_id),
        ("mcp-connections", MCP.connection_id),
    ],
)
def test_manage_only_patch(
    tmp_path: Path,
    store: AsyncMock,
    collection: str,
    identifier: str,
) -> None:
    response = _client(tmp_path, store).patch(
        f"{PREFIX}/{collection}/{identifier}",
        headers=AUTH | {"If-Match": '"1"'},
        json={"enabled": False},
    )
    assert response.status_code == 200
    assert response.headers["etag"] == '"2"'
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["enabled"] is False
    for secret in ("scope", "credential_ref", "artifact_ref", "://secret"):
        assert secret not in response.text


@pytest.mark.parametrize(
    "body",
    [
        "",
        "null",
        "[]",
        "{}",
        '{"enabled":1}',
        '{"enabled":"false"}',
        '{"enabled":false,"revision":1}',
        '{"enabled":false,"enabled":true}',
    ],
)
def test_invalid_body(tmp_path: Path, store: AsyncMock, body: str) -> None:
    response = _client(tmp_path, store).patch(
        f"{PREFIX}/skill-installations/{SKILL.installation_id}",
        headers=AUTH | {"If-Match": '"1"'},
        content=body,
    )
    assert response.status_code == 422
    assert store.mock_calls == []


@pytest.mark.parametrize("value", ["1", 'W/"1"', '"0"', '"01"', "*", '"1", "2"'])
def test_invalid_match(tmp_path: Path, store: AsyncMock, value: str) -> None:
    response = _client(tmp_path, store).patch(
        f"{PREFIX}/skill-installations/{SKILL.installation_id}",
        headers=AUTH | {"If-Match": value},
        json={"enabled": False},
    )
    assert response.status_code == 422
    assert store.mock_calls == []


def test_failures_and_read_etag(tmp_path: Path, store: AsyncMock) -> None:
    client = _client(tmp_path, store, scopes=["extensions.read", "extensions.manage"])
    path = f"{PREFIX}/skill-installations/{SKILL.installation_id}"
    assert client.get(path, headers=AUTH).headers["etag"] == '"1"'
    store.reset_mock()
    assert client.patch(path, headers=AUTH, json={"enabled": False}).status_code == 428
    assert client.patch(path, json={"enabled": False}).status_code == 401
    headers = AUTH | {"If-Match": '"1"'}
    assert client.patch(path + "?x=y", headers=headers, json={"enabled": False}).status_code == 422
    assert client.patch(path, headers=headers, content=b" " * 8193).status_code == 413
    duplicate = list(headers.items()) + [("If-Match", '"1"')]
    assert client.patch(path, headers=duplicate, json={"enabled": False}).status_code == 422
    assert store.mock_calls == []
    assert (
        client.patch(path, headers=AUTH | {"If-Match": '"2"'}, json={"enabled": True}).status_code
        == 409
    )
    store.save_skill.side_effect = ExtensionRevisionConflictError()
    assert client.patch(path, headers=headers, json={"enabled": False}).status_code == 409
    store.get_skill.side_effect = RuntimeError("credential://secret")
    response = client.patch(path, headers=headers, json={"enabled": False})
    assert response.status_code == 503
    assert "secret" not in response.text


def test_enabling_duplicate_skill_returns_conflict_not_unavailable(
    tmp_path: Path,
    store: AsyncMock,
) -> None:
    store.save_skill.side_effect = ExtensionSkillConflictError(
        "another enabled installation already owns this Skill"
    )
    response = _client(tmp_path, store).patch(
        f"{PREFIX}/skill-installations/{SKILL.installation_id}",
        headers=AUTH | {"If-Match": '"1"'},
        json={"enabled": False},
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "scopes,enabled,local,status",
    [
        (["extensions.read"], True, False, 403),
        (["extensions.read"], False, False, 405),
        (["extensions.manage"], True, True, 404),
    ],
)
def test_disabled_or_denied(
    tmp_path: Path, store: AsyncMock, scopes: list[str], enabled: bool, local: bool, status: int
) -> None:
    response = _client(tmp_path, store, scopes=scopes, enabled=enabled, local=local).patch(
        f"{PREFIX}/skill-installations/{SKILL.installation_id}",
        headers=AUTH | {"If-Match": '"1"'},
        json={"enabled": False},
    )
    assert response.status_code == status
    assert store.mock_calls == []


def test_cors(tmp_path: Path, store: AsyncMock) -> None:
    client = _client(tmp_path, store)
    path = f"{PREFIX}/skill-installations/{SKILL.installation_id}"
    response = client.options(
        path,
        headers={
            "Origin": "https://host.example.com",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "If-Match,Authorization,Content-Type",
        },
    )
    assert response.status_code == 200
    assert "if-match" in response.headers["access-control-allow-headers"].lower()
    response = client.patch(
        path,
        headers=AUTH
        | {
            "If-Match": '"1"',
            "Origin": "https://host.example.com",
        },
        json={"enabled": False},
    )
    assert response.headers["access-control-expose-headers"] == "ETag"


def test_body_stream_stops_at_limit(store: AsyncMock) -> None:
    calls = 0

    async def receive() -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls > 2:
            raise AssertionError("Body stream should stop before consuming remaining chunks")
        return {"type": "http.request", "body": b" " * 4097, "more_body": True}

    request = Request(
        {
            "type": "http",
            "method": "PATCH",
            "scheme": "https",
            "path": f"{PREFIX}/skill-installations/{SKILL.installation_id}",
            "query_string": b"",
            "headers": [(b"if-match", b'"1"')],
            "server": ("test", 443),
            "state": {"verified_host_grant": _verified()},
        },
        receive=receive,
    )
    response = asyncio.run(
        extension_read_response(
            request,
            store=store,
            deployment="cloud",
            manage_enabled=True,
        )
    )
    assert response is not None and response.status_code == 413
    assert calls == 2
    assert store.mock_calls == []


def test_noop_cross_scope_and_methods(tmp_path: Path, store: AsyncMock) -> None:
    client = _client(tmp_path, store, scopes=["extensions.read", "extensions.manage"])
    path = f"{PREFIX}/skill-installations/{SKILL.installation_id}"
    headers = AUTH | {"If-Match": '"1"'}
    response = client.patch(path, headers=headers, json={"enabled": True})
    assert response.status_code == 200 and response.headers["etag"] == '"1"'
    store.save_skill.assert_not_called()
    store.get_skill.return_value = SKILL.model_copy(
        update={
            "scope": SKILL.scope.model_copy(update={"workspace_id": "other"}),
        }
    )
    assert client.patch(path, headers=headers, json={"enabled": False}).status_code == 404
    store.save_skill.assert_not_called()
    assert client.delete(path, headers=AUTH).headers["allow"] == "GET, PATCH"
    collection = client.patch(f"{PREFIX}/skill-installations", headers=headers)
    assert collection.headers["allow"] == "GET, POST"
    assert client.patch(f"{PREFIX}/unknown/id", headers=headers).status_code == 404


@pytest.mark.parametrize("value,expected", [(None, False), ("true", True), ("false", False)])
def test_manage_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str | None, expected: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    env = {} if value is None else {"ZEBRA_CLOUD_EXTENSIONS_MANAGE_ENABLED": value}
    assert load_settings(env=env).cloud_extensions_manage_enabled is expected
