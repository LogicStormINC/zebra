import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from agent_core.ports.skill_publications import SkillPublicationNotFoundError
from pydantic import ValidationError
from starlette.requests import Request
from zebra_agent_api.extension_reads import extension_read_response

from tests.agent_core.test_skill_installation_creation import installation_store, payload
from tests.agent_security.test_extension_authority import _verified
from tests.api.test_extension_reads import AUTH, PREFIX
from tests.api.test_extension_updates import _client

PATH = PREFIX + "/skill-installations"
HEADERS = AUTH | {"Idempotency-Key": "key"}


@pytest.fixture
def store() -> AsyncMock:
    return installation_store()


def test_create_replay_and_conflict(tmp_path: Path, store: AsyncMock) -> None:
    client = _client(tmp_path, store)
    request = payload(store)
    response = client.post(PATH, headers=HEADERS, json=request)
    assert response.status_code == 201 and response.headers["etag"] == '"1"'
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["location"] == PATH + "/" + response.json()["installation_id"]
    assert response.json()["enabled"] is False
    assert all(secret not in response.text for secret in ("artifact_ref", "scope", "receipt"))
    original = store.save_skill.await_args.kwargs["installation"]
    store.get_skill_creation.side_effect = None
    store.get_skill_creation.return_value = original
    store.get_skill.return_value = original.model_copy(update={"revision": 2, "enabled": True})
    replay = client.post(PATH, headers=HEADERS, json=request)
    assert replay.status_code == 200 and replay.headers["etag"] == '"2"'
    assert replay.json()["enabled"] is True
    assert client.post(PATH, headers=HEADERS,
                       json=request | {"version_id": "unknown"}).status_code == 409


@pytest.mark.parametrize("body", [
    "", "null", "[]", "{}", '{"skill_id":1,"version_id":"v"}',
    '{"skill_id":"s","version_id":null}', '{"skill_id":" ","version_id":"v"}',
    '{"skill_id":"s","version_id":"v","version_id":"w"}',
    *[json.dumps({"skill_id": "s", "version_id": "v", field: "x"}) for field in
      ("scope", "enabled", "revision", "installation_id", "artifact_ref",
       "content_digest", "version")],
])
def test_strict_body(tmp_path: Path, store: AsyncMock, body: str) -> None:
    assert _client(tmp_path, store).post(PATH, headers=HEADERS, content=body).status_code == 422
    assert not store.mock_calls


def test_headers_and_bounded_body(tmp_path: Path, store: AsyncMock) -> None:
    client = _client(tmp_path, store)
    for key in ("", "has space", "x" * 129):
        assert client.post(PATH, headers=AUTH | {"Idempotency-Key": key},
                           json=payload(store)).status_code == 422
    assert client.post(PATH, headers=AUTH, json=payload(store)).status_code == 422
    assert client.post(PATH, headers=list(HEADERS.items()) + [("Idempotency-Key", "other")],
                       json=payload(store)).status_code == 422
    assert client.post(PATH + "?scope=x", headers=HEADERS, json=payload(store)).status_code == 422
    assert client.post(PATH, headers=HEADERS, content=b" " * 8193).status_code == 413
    assert not store.mock_calls


@pytest.mark.parametrize("scopes,enabled,local,status", [
    (["extensions.read"], True, False, 403),
    (["extensions.read"], False, False, 405),
    (["extensions.manage"], True, True, 404),
    (["session.write"], True, False, 403),
])
def test_authority_flags(tmp_path: Path, store: AsyncMock, scopes: list[str],
                         enabled: bool, local: bool, status: int) -> None:
    assert _client(tmp_path, store, scopes=scopes, enabled=enabled, local=local).post(
        PATH, headers=HEADERS, json=payload(store),
    ).status_code == status
    assert not store.mock_calls


@pytest.mark.parametrize("operation", ["get_skill_creation", "get_skill_publication", "save_skill"])
def test_corrupt_storage_is_503(tmp_path: Path, store: AsyncMock, operation: str) -> None:
    getattr(store, operation).side_effect = ValidationError.from_exception_data("secret", [])
    response = _client(tmp_path, store).post(PATH, headers=HEADERS, json=payload(store))
    assert response.status_code == 503 and "secret" not in response.text


def test_unknown_publication(tmp_path: Path, store: AsyncMock) -> None:
    store.get_skill_publication.side_effect = SkillPublicationNotFoundError("secret")
    response = _client(tmp_path, store).post(PATH, headers=HEADERS, json=payload(store))
    assert response.status_code == 404 and "secret" not in response.text
    store.save_skill.assert_not_awaited()


@pytest.mark.parametrize("change,status", [("publishing", 404), ("foreign", 404),
                                          ("corrupt", 503), ("type", 503)])
def test_publication_responses(tmp_path: Path, store: AsyncMock, change: str, status: int) -> None:
    request = payload(store)
    publication = store.get_skill_publication.return_value
    if change == "publishing":
        result = publication.model_copy(update={"state": "publishing", "receipt": None})
    elif change == "foreign":
        from agent_tools.skill_publications import _candidate

        from tests.agent_tools.test_skill_publications import archive

        result = _candidate(archive(), publication.scope.model_copy(
            update={"principal_id": "foreign-secret"},
        ), "test")
    elif change == "corrupt":
        result = publication.model_copy(update={"manifest": ()})
    else:
        result = None
    store.get_skill_publication.return_value = result
    response = _client(tmp_path, store).post(PATH, headers=HEADERS, json=request)
    assert response.status_code == status and "foreign-secret" not in response.text
    store.save_skill.assert_not_awaited()


@pytest.mark.parametrize("getter", ["get_skill_creation", "get_skill"])
@pytest.mark.parametrize("change,status", [("scope", 404), ("installation_id", 404),
                                          ("revision", 503), ("type", 503), ("failure", 503)])
def test_replay_adapter_failures(tmp_path: Path, store: AsyncMock, getter: str,
                                 change: str, status: int) -> None:
    client = _client(tmp_path, store)
    request = payload(store)
    assert client.post(PATH, headers=HEADERS, json=request).status_code == 201
    original = store.save_skill.await_args.kwargs["installation"]
    store.get_skill_creation.side_effect = None
    store.get_skill_creation.return_value = store.get_skill.return_value = original
    operation = getattr(store, getter)
    if change == "failure":
        operation.side_effect = ValidationError.from_exception_data("secret", [])
    elif change == "type":
        operation.return_value = None
    else:
        operation.return_value = original.model_copy(update={change: {
            "scope": original.scope.model_copy(update={"principal_id": "foreign-secret"}),
            "installation_id": "wrong-secret", "revision": 0,
        }[change]})
    response = client.post(PATH, headers=HEADERS, json=request)
    assert response.status_code == status and "secret" not in response.text


@pytest.mark.parametrize("operation", ["get_skill_creation", "get_skill_publication", "save_skill"])
def test_cancellation_propagates(store: AsyncMock, operation: str) -> None:
    getattr(store, operation).side_effect = asyncio.CancelledError()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": json.dumps(payload(store)).encode(),
                "more_body": False}

    request = Request({
        "type": "http", "method": "POST", "scheme": "https", "path": PATH,
        "query_string": b"", "headers": [(b"idempotency-key", b"key")],
        "server": ("test", 443), "state": {"verified_host_grant": _verified()},
    }, receive=receive)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(extension_read_response(request, store=store, deployment="cloud",
                                            manage_enabled=True))
