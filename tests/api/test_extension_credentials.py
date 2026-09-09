"""Credential ingress never reads secrets back or accepts client authority."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from agent_core.domain.mcp_credentials import McpCredentialProtectionError
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionRevisionConflictError,
    ExtensionStore,
)
from agent_security.mcp_credential_management import McpCredentialManagement
from agent_storage import sqlite_control_plane_stores
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app

from tests.agent_security.test_extension_authority import _verified
from tests.agent_storage import test_mcp_credential_management as fixtures
from tests.api.test_extension_reads import AUTH, MCP, Authorizer
from tests.api.test_host_auth_http import _cloud_settings, _local_settings

dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn
protector = fixtures.protector
PATH = "/v1/extensions/mcp-connections/connection-a/credentials"
HEADERS = AUTH | {"If-Match": '"1"'}
TOKEN = "private-fixture-token"


def client(tmp_path, service, *, scopes=None, enabled=True, local=False):
    database = tmp_path / "credentials.sqlite"
    settings = _local_settings() if local else _cloud_settings("postgresql://unused/zebra")
    return TestClient(
        create_http_app(
            database,
            settings=replace(settings, cloud_extensions_manage_enabled=enabled),
            stores=sqlite_control_plane_stores(database),
            extension_store=AsyncMock(spec=ExtensionStore),
            mcp_credential_management=service,
            host_grant_authorizer=Authorizer(
                _verified(scopes=scopes if scopes is not None else ["extensions.manage"])
            ),
        )
    )


@pytest.fixture
def service():
    result = AsyncMock(spec=McpCredentialManagement)
    result.provision.return_value = MCP.model_copy(update={"revision": 2})
    result.revoke.return_value = MCP.model_copy(update={"revision": 2})
    return result


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_metadata_only(tmp_path, service, method):
    response = client(tmp_path, service).request(
        method, PATH, headers=HEADERS, **({"json": {"token": TOKEN}} if method == "POST" else {})
    )
    assert response.status_code == 200
    assert response.headers["etag"] == '"2"'
    assert response.headers["cache-control"] == "no-store"
    assert not any(
        value in response.text for value in (TOKEN, "credential_ref", "scope", "credential://")
    )
    call = service.provision if method == "POST" else service.revoke
    assert call.await_args.kwargs["expected_connection_revision"] == 1
    assert call.await_args.kwargs["connection_id"] == MCP.connection_id


@pytest.mark.parametrize("options", [{"enabled": False}, {"local": True}])
def test_hidden(tmp_path, service, options):
    assert (
        client(tmp_path, service, **options)
        .post(PATH, headers=HEADERS, json={"token": TOKEN})
        .status_code
        == 404
    )
    assert service.mock_calls == []


def test_absent_composition(tmp_path):
    assert (
        client(tmp_path, None).post(PATH, headers=HEADERS, json={"token": TOKEN}).status_code == 404
    )


@pytest.mark.parametrize("scopes", [["agent.run"], ["extensions.read"]])
def test_manage_required(tmp_path, service, scopes):
    assert (
        client(tmp_path, service, scopes=scopes)
        .post(PATH, headers=HEADERS, json={"token": TOKEN})
        .status_code
        == 403
    )
    assert service.mock_calls == []


@pytest.mark.parametrize(
    "body",
    [
        "",
        "null",
        "[]",
        "{}",
        '{"token":1}',
        '{"token":""}',
        '{"token":"a b"}',
        '{"token":"a\\nb"}',
        '{"token":"a","token":"b"}',
        '{"token":"a","scope":"other"}',
    ],
)
def test_invalid_body(tmp_path, service, body):
    assert client(tmp_path, service).post(PATH, headers=HEADERS, content=body).status_code == 422
    assert service.mock_calls == []


def test_protocol_boundaries(tmp_path, service):
    api = client(tmp_path, service)
    assert api.post(PATH, json={"token": TOKEN}).status_code == 401
    assert api.post(PATH, headers=AUTH, json={"token": TOKEN}).status_code == 428
    for match in ['W/"1"', '"0"', '"01"', "*", '"1", "2"']:
        assert (
            api.post(PATH, headers=AUTH | {"If-Match": match}, json={"token": TOKEN}).status_code
            == 422
        )
    assert (
        api.post(
            PATH, headers=list(HEADERS.items()) + [("If-Match", '"1"')], json={"token": TOKEN}
        ).status_code
        == 422
    )
    assert api.post(PATH, headers=HEADERS, content=b" " * 8193).status_code == 413
    assert api.post(PATH + "?token=x", headers=HEADERS, json={"token": TOKEN}).status_code == 422
    assert api.request("DELETE", PATH, headers=HEADERS, json={}).status_code == 422
    response = api.get(PATH, headers=AUTH)
    assert response.status_code == 405 and response.headers["allow"] == "POST, DELETE"
    assert service.mock_calls == []


@pytest.mark.parametrize(
    "error,status",
    [
        (ExtensionNotFoundError, 404),
        (ExtensionRevisionConflictError, 409),
        (McpCredentialProtectionError, 503),
        (RuntimeError, 503),
    ],
)
def test_scrubbed_failure(tmp_path, service, error, status):
    service.provision.side_effect = error(TOKEN)
    response = client(tmp_path, service).post(PATH, headers=HEADERS, json={"token": TOKEN})
    assert response.status_code == status and TOKEN not in response.text


def test_wrong_identity_not_returned(tmp_path, service):
    service.provision.return_value = MCP.model_copy(update={"connection_id": "foreign"})
    assert (
        client(tmp_path, service).post(PATH, headers=HEADERS, json={"token": TOKEN}).status_code
        == 404
    )


def test_postgres_http_lifecycle(tmp_path, dsn, protector):
    management, store, _, scope = fixtures.management(dsn, protector)
    api = client(tmp_path, management)
    path = PATH.replace("connection-a", "mcp")
    response = api.post(path, headers=HEADERS, json={"token": TOKEN})
    assert response.status_code == 200 and response.json()["auth_state"] == "ready"
    assert response.json()["enabled"] is False
    current = asyncio.run(store.get_connection(scope=scope, connection_id="mcp"))
    encrypted = asyncio.run(
        store.get(scope=scope, connection_id="mcp", credential_ref=current.credential_ref)
    )
    assert protector.unseal(encrypted.binding, encrypted.envelope).value == TOKEN
    assert TOKEN not in response.text
    assert api.post(path, headers=HEADERS, json={"token": TOKEN}).status_code == 409
    response = api.delete(path, headers=AUTH | {"If-Match": '"2"'})
    assert response.status_code == 200 and response.json()["auth_state"] == "revoked"
    assert response.headers["etag"] == '"3"'
    assert asyncio.run(store.get_connection(scope=scope, connection_id="mcp")).revision == 3
