"""Read-only cloud extension HTTP boundaries with injected async stores."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent_core.domain.extensions import McpConnection, SkillInstallation, SkillVersion
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionPageRequest,
    ExtensionStore,
    McpConnectionPage,
    SkillInstallationPage,
)
from agent_security.extension_authority import extension_scope_from_grant
from agent_storage import sqlite_control_plane_stores
from fastapi.testclient import TestClient
from starlette.requests import Request
from zebra_agent_api import create_http_app
from zebra_agent_api.extension_reads import extension_read_response
from zebra_agent_api.http import HostGrantHttpRequest

from tests.agent_security.test_extension_authority import _verified
from tests.api.test_host_auth_http import _cloud_settings, _local_settings

PREFIX = "/v1/extensions"
AUTH = {"Authorization": "Bearer user-a"}
VERIFIED = _verified()
SCOPE = extension_scope_from_grant(VERIFIED, permission="extensions.read")
SKILL = SkillInstallation(
    scope=SCOPE,
    installation_id="installed-a",
    revision=1,
    version=SkillVersion(
        skill_id="skill-a",
        version_id="v1",
        artifact_ref="artifact://secret",
        content_digest="a" * 64,
    ),
)
MCP = McpConnection(
    scope=SCOPE,
    connection_id="connection-a",
    revision=1,
    endpoint="https://mcp.example/api",
    auth_mode="bearer",
    auth_state="ready",
    credential_ref="credential://secret",
)


@dataclass
class Authorizer:
    verified: object = VERIFIED
    allowed_origins: tuple[str, ...] = ("https://host.example.com",)

    def authorize(self, request: HostGrantHttpRequest) -> object:
        assert request.authorization == AUTH["Authorization"]
        return self.verified


def _client(
    tmp_path: Path,
    store: ExtensionStore | None,
    *,
    verified: object = VERIFIED,
    local: bool = False,
) -> TestClient:
    database = tmp_path / "extensions.sqlite"
    return TestClient(
        create_http_app(
            database,
            settings=_local_settings() if local else _cloud_settings("postgresql://unused/zebra"),
            stores=sqlite_control_plane_stores(database),
            host_grant_authorizer=Authorizer(verified),
            extension_store=store,
        )
    )


@pytest.fixture
def store() -> AsyncMock:
    result = AsyncMock(spec=ExtensionStore)
    result.get_skill.return_value = SKILL
    result.get_mcp.return_value = MCP
    result.list_skills.return_value = SkillInstallationPage(items=(SKILL,), next_cursor="next-a")
    result.list_mcp.return_value = McpConnectionPage(items=(MCP,), next_cursor="next-b")
    return result


@pytest.mark.parametrize("path", ["skill-installations", "mcp-connections"])
def test_lists_and_details_await_scoped_store_without_private_refs(
    tmp_path: Path, store: AsyncMock, path: str
) -> None:
    client = _client(tmp_path, store)
    response = client.get(f"{PREFIX}/{path}?limit=1&cursor=previous", headers=AUTH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    skill = path == "skill-installations"
    listing = store.list_skills if skill else store.list_mcp
    listing.assert_awaited_once_with(
        scope=SCOPE, page=ExtensionPageRequest(limit=1, cursor="previous")
    )
    assert response.json()["next_cursor"] == ("next-a" if skill else "next-b")
    detail = client.get(f"{PREFIX}/{path}/config-a", headers=AUTH)
    assert detail.status_code == 200
    assert detail.json() == response.json()["items"][0]
    getter = store.get_skill if skill else store.get_mcp
    getter.assert_awaited_once_with(
        scope=SCOPE, **({"installation_id": "config-a"} if skill else {"connection_id": "config-a"})
    )
    for body in (response.text, detail.text):
        for private in ("scope", "credential_ref", "artifact_ref", "://secret", "subject-a"):
            assert private not in body
    store.save_skill.assert_not_called()
    store.save_mcp.assert_not_called()


def test_default_page_and_empty_list(tmp_path: Path, store: AsyncMock) -> None:
    store.list_skills.return_value = SkillInstallationPage(items=())
    response = _client(tmp_path, store).get(f"{PREFIX}/skill-installations", headers=AUTH)
    assert response.json() == {"items": [], "next_cursor": None}
    store.list_skills.assert_awaited_once_with(scope=SCOPE, page=ExtensionPageRequest())


@pytest.mark.parametrize("local", [True, False])
def test_disabled_store_and_local_profile(tmp_path: Path, store: AsyncMock, local: bool) -> None:
    client = _client(tmp_path, store if local else None, local=local)
    response = client.get(f"{PREFIX}/skill-installations", headers=AUTH)
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert store.mock_calls == []
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("scopes", [["agent.run"], ["extensions.manage"]])
def test_read_permission_is_explicit(tmp_path: Path, store: AsyncMock, scopes: list[str]) -> None:
    client = _client(tmp_path, store, verified=_verified(scopes=scopes))
    response = client.get(f"{PREFIX}/skill-installations", headers=AUTH)
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    assert response.headers["cache-control"] == "no-store"
    assert store.mock_calls == []


def test_missing_and_duck_typed_grants_fail_closed(tmp_path: Path, store: AsyncMock) -> None:
    client = _client(tmp_path, store, verified=SimpleNamespace(**vars(VERIFIED)))
    denied = client.get(f"{PREFIX}/mcp-connections", headers=AUTH)
    assert denied.status_code == 403
    missing = client.get(f"{PREFIX}/mcp-connections")
    assert missing.status_code == 401
    assert missing.json()["code"] == "authorization_required"
    assert missing.headers["cache-control"] == "no-store"
    assert store.mock_calls == []


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "limit=no",
        "limit=1.5",
        "limit=1&limit=2",
        "cursor=a&cursor=b",
        "cursor=",
        "cursor=" + "a" * 513,
        "namespace_id=other",
        "principal_id=other",
        "workspace_id=other",
        "authority_issuer=other",
        "sub=other",
        "iss=other",
        "unknown=1",
    ],
)
def test_invalid_queries_never_reach_store(tmp_path: Path, store: AsyncMock, query: str) -> None:
    response = _client(tmp_path, store).get(f"{PREFIX}/skill-installations?{query}", headers=AUTH)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert store.mock_calls == []


def test_details_reject_all_query_parameters(tmp_path: Path, store: AsyncMock) -> None:
    response = _client(tmp_path, store).get(f"{PREFIX}/mcp-connections/id?limit=1", headers=AUTH)
    assert response.status_code == 422
    assert store.mock_calls == []


@pytest.mark.parametrize("identifier", ["a" * 513, "%20untrimmed", "control%00id"])
def test_invalid_detail_ids_never_reach_store(
    tmp_path: Path, store: AsyncMock, identifier: str
) -> None:
    response = _client(tmp_path, store).get(f"{PREFIX}/mcp-connections/{identifier}", headers=AUTH)
    assert response.status_code == 422
    assert store.mock_calls == []


@pytest.mark.parametrize(
    "method", ["HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"]
)
def test_non_get_methods_and_unknown_paths(tmp_path: Path, store: AsyncMock, method: str) -> None:
    client = _client(tmp_path, store)
    for path in ("skill-installations", "mcp-connections/id"):
        response = client.request(method, f"{PREFIX}/{path}", headers=AUTH, content=b"invalid json")
        assert response.status_code == 405
        assert response.headers["allow"] == "GET"
        assert response.headers["cache-control"] == "no-store"
    assert client.request(method, f"{PREFIX}/unknown", headers=AUTH).status_code == 404
    assert store.mock_calls == []


@pytest.mark.parametrize("claim", ["iss", "sub", "namespace_id", "workspace_ref"])
@pytest.mark.parametrize("path", ["skill-installations", "mcp-connections"])
def test_each_scope_coordinate_is_enforced_on_lists_and_details(
    tmp_path: Path, store: AsyncMock, claim: str, path: str
) -> None:
    verified = _verified(**{claim: "https://other.example" if claim == "iss" else "other"})
    client = _client(tmp_path, store, verified=verified)
    listing = client.get(f"{PREFIX}/{path}", headers=AUTH)
    detail = client.get(f"{PREFIX}/{path}/foreign", headers=AUTH)
    # A faulty adapter returned somebody else's record: never serialize it.
    assert listing.status_code == detail.status_code == 404
    getter = store.get_skill if path == "skill-installations" else store.get_mcp
    assert getter.await_args.kwargs["scope"] == extension_scope_from_grant(
        verified, permission="extensions.read"
    )
    getter.side_effect = ExtensionNotFoundError("secret internal detail")
    unknown = client.get(f"{PREFIX}/{path}/unknown", headers=AUTH)
    assert unknown.status_code == 404
    assert unknown.json() == detail.json() == listing.json()


def test_checks_every_page_item(tmp_path: Path, store: AsyncMock) -> None:
    foreign = SKILL.model_copy(update={"scope": SCOPE.model_copy(update={"principal_id": "other"})})
    store.list_skills.return_value = SkillInstallationPage(items=(SKILL, foreign))
    response = _client(tmp_path, store).get(f"{PREFIX}/skill-installations", headers=AUTH)
    assert response.status_code == 404
    assert "items" not in response.json()


def test_store_failure_is_sanitized(tmp_path: Path, store: AsyncMock) -> None:
    store.list_mcp.side_effect = RuntimeError("postgresql://private:password@internal credential")
    response = _client(tmp_path, store).get(f"{PREFIX}/mcp-connections", headers=AUTH)
    assert response.status_code == 503
    assert response.json() == {
        "code": "service_unavailable",
        "message": "Extension configuration is temporarily unavailable.",
        "retryable": True,
        "action": None,
    }
    assert response.headers["cache-control"] == "no-store"


def test_store_cancellation_propagates(store: AsyncMock) -> None:
    store.list_skills.side_effect = asyncio.CancelledError()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"{PREFIX}/skill-installations",
            "query_string": b"",
            "headers": [],
        }
    )
    request.state.verified_host_grant = VERIFIED
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(extension_read_response(request, store=store, deployment="cloud"))
