import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from agent_core.ports.extensions import ExtensionRevisionConflictError, ExtensionStore
from pydantic import ValidationError
from starlette.requests import Request
from zebra_agent_api.extension_reads import extension_read_response

from tests.agent_core.test_mcp_connections import PAYLOAD
from tests.agent_security.test_extension_authority import _verified
from tests.api.test_extension_reads import AUTH, PREFIX
from tests.api.test_extension_updates import _client

PATH = f"{PREFIX}/mcp-connections"
HEADERS = AUTH | {"Idempotency-Key": "test-key"}


@pytest.fixture
def store() -> AsyncMock:
    return AsyncMock(spec=ExtensionStore)


def test_create_and_replay(tmp_path: Path, store: AsyncMock) -> None:
    client = _client(tmp_path, store)
    response = client.post(PATH, headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 201
    assert response.headers["etag"] == '"1"'
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["location"] == PATH + "/" + response.json()["connection_id"]
    assert response.json()["enabled"] is False
    for secret in ("scope", "credential_ref", "test-key"):
        assert secret not in response.text
    original = store.save_mcp.await_args.kwargs["connection"]
    store.save_mcp.side_effect = ExtensionRevisionConflictError()
    store.get_mcp_creation.return_value = original
    store.get_mcp.return_value = original.model_copy(update={"revision": 2, "enabled": True})
    replay = client.post(PATH, headers=HEADERS, json=PAYLOAD)
    assert replay.status_code == 200 and replay.headers["etag"] == '"2"'
    assert replay.json()["enabled"] is True
    assert client.post(PATH, headers=HEADERS,
                       json=PAYLOAD | {"auth_mode": "oauth"}).status_code == 409


@pytest.mark.parametrize("body", [
    "", "null", "[]", "{}", '{"endpoint":1}', '{"endpoint":null}',
    '{"endpoint":"https://a","endpoint":"https://b"}',
    '{"endpoint":"https://a","transport":"stdio"}',
    '{"endpoint":"http://a"}', '{"endpoint":"https://user:secret@a"}',
    '{"endpoint":"https://a","auth_mode":"unknown"}',
    '{"endpoint":"https://a","enabled":false}',
    '{"endpoint":"https://a","credential_ref":"credential://secret"}',
    '{"endpoint":"https://a","auth_state":"ready"}',
    '{"endpoint":"https://a","scope":{}}',
    '{"endpoint":"https://a","connection_id":"a"}',
    '{"endpoint":"https://a","display_name":"a"}',
])
def test_strict_body(tmp_path: Path, store: AsyncMock, body: str) -> None:
    assert _client(tmp_path, store).post(PATH, headers=HEADERS, content=body).status_code == 422
    assert not store.mock_calls


def test_headers_limits_queries_errors(tmp_path: Path, store: AsyncMock) -> None:
    client = _client(tmp_path, store)
    for key in ("", "has space", "x" * 129):
        assert client.post(PATH, headers=AUTH | {"Idempotency-Key": key},
                           json=PAYLOAD).status_code == 422
    assert client.post(PATH, headers=AUTH, json=PAYLOAD).status_code == 422
    assert client.post(PATH, headers=list(HEADERS.items()) + [("Idempotency-Key", "other")],
                       json=PAYLOAD).status_code == 422
    assert client.post(PATH + "?scope=x", headers=HEADERS, json=PAYLOAD).status_code == 422
    assert client.post(PATH, headers=HEADERS, content=b" " * 8193).status_code == 413
    assert client.post(PATH, json=PAYLOAD).status_code == 401
    assert not store.mock_calls
    store.save_mcp.side_effect = RuntimeError("credential://secret")
    response = client.post(PATH, headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 503 and "secret" not in response.text


@pytest.mark.parametrize("scopes,enabled,local,status", [
    (["extensions.read"], True, False, 403),
    (["extensions.read"], False, False, 405),
    (["extensions.manage"], True, True, 404),
    (["session.write"], True, False, 403),
])
def test_authority_flags(tmp_path: Path, store: AsyncMock, scopes: list[str],
                         enabled: bool, local: bool, status: int) -> None:
    response = _client(tmp_path, store, scopes=scopes, enabled=enabled, local=local).post(
        PATH, headers=HEADERS, json=PAYLOAD,
    )
    assert response.status_code == status and not store.mock_calls


def test_cors_allow(tmp_path: Path, store: AsyncMock) -> None:
    client = _client(tmp_path, store, scopes=["extensions.read", "extensions.manage"])
    response = client.options(PATH, headers={
        "Origin": "https://host.example.com", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Idempotency-Key,Authorization,Content-Type",
    })
    assert response.status_code == 200
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()
    assert client.delete(PATH, headers=AUTH).headers["allow"] == "GET, POST"
    assert client.post(PREFIX + "/skill-installations", headers=HEADERS,
                       json=PAYLOAD).status_code == 422


@pytest.mark.parametrize("getter", ["get_mcp_creation", "get_mcp"])
def test_foreign_adapter_response_is_hidden(tmp_path: Path, store: AsyncMock, getter: str) -> None:
    client = _client(tmp_path, store)
    assert client.post(PATH, headers=HEADERS, json=PAYLOAD).status_code == 201
    original = store.save_mcp.await_args.kwargs["connection"]
    store.save_mcp.side_effect = ExtensionRevisionConflictError()
    store.get_mcp_creation.return_value = original
    store.get_mcp.return_value = original
    getattr(store, getter).return_value = original.model_copy(update={
        "scope": original.scope.model_copy(update={"principal_id": "foreign-user"}),
    })
    response = client.post(PATH, headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 404 and "foreign-user" not in response.text


def test_store_cancellation_propagates(store: AsyncMock) -> None:
    store.save_mcp.side_effect = asyncio.CancelledError()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b'{"endpoint":"https://mcp.example"}',
                "more_body": False}

    request = Request({
        "type": "http", "method": "POST", "scheme": "https", "path": PATH,
        "query_string": b"", "headers": [(b"idempotency-key", b"key")],
        "server": ("test", 443), "state": {"verified_host_grant": _verified()},
    }, receive=receive)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(extension_read_response(request, store=store, deployment="cloud",
                                            manage_enabled=True))


@pytest.mark.parametrize("operation,malformed", [
    ("save_mcp", False), ("get_mcp_creation", False), ("get_mcp", False),
    ("get_mcp_creation", True), ("get_mcp", True),
])
def test_corrupt_storage_is_sanitized_server_failure(
    tmp_path: Path, store: AsyncMock, operation: str, malformed: bool,
) -> None:
    client = _client(tmp_path, store)
    assert client.post(PATH, headers=HEADERS, json=PAYLOAD).status_code == 201
    original = store.save_mcp.await_args.kwargs["connection"]
    store.save_mcp.side_effect = ExtensionRevisionConflictError()
    store.get_mcp_creation.return_value = original
    store.get_mcp.return_value = original
    if malformed:
        getattr(store, operation).return_value = original.model_copy(update={
            "endpoint": "https://user:secret@example.com",
        })
    else:
        getattr(store, operation).side_effect = ValidationError.from_exception_data("secret", [])
    response = client.post(PATH, headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 503
    assert response.json()["retryable"] is True and "secret" not in response.text


@pytest.mark.parametrize("cancel", [False, True])
def test_stream_limit_and_cancellation(store: AsyncMock, cancel: bool) -> None:
    calls = 0

    async def receive() -> dict[str, object]:
        nonlocal calls
        calls += 1
        if cancel:
            raise asyncio.CancelledError()
        assert calls <= 2
        return {"type": "http.request", "body": b" " * 4097, "more_body": True}

    request = Request({
        "type": "http", "method": "POST", "scheme": "https", "path": PATH,
        "query_string": b"", "headers": [(b"idempotency-key", b"key")],
        "server": ("test", 443), "state": {"verified_host_grant": _verified()},
    }, receive=receive)
    operation = extension_read_response(request, store=store, deployment="cloud",
                                        manage_enabled=True)
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(operation)
    else:
        response = asyncio.run(operation)
        assert response is not None and response.status_code == 413 and calls == 2
    assert not store.mock_calls
