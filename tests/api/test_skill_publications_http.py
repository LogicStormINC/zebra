"""Upload boundary rejects unauthorized requests before reading or storing bytes."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from agent_core.ports.skill_publications import SkillPublicationStorePort
from agent_tools.skill_publications import SkillPublicationService, _candidate
from starlette.requests import Request
from zebra_agent_api.skill_publications import skill_publication_response

from tests.agent_security.test_extension_authority import _verified
from tests.agent_tools.test_skill_publications import Objects, archive
from tests.api.test_extension_reads import SCOPE, VERIFIED


def request(path: str = "", method: str = "POST", *, verified: object = VERIFIED,
            headers: list[tuple[bytes, bytes]] | None = None, receive: object = None) -> Request:
    result = Request({"type": "http", "method": method, "path": "/v1/extensions/skill-packages"
                      + path, "headers": headers if headers is not None else [
                          (b"content-type", b"application/zip"), (b"idempotency-key", b"one")],
                      "query_string": b""}, receive or AsyncMock(return_value={
                          "type": "http.request", "body": archive(), "more_body": False}))
    result.state.verified_host_grant = verified
    return result


def respond(req: Request, store: AsyncMock, **kwargs: object) -> object:
    return asyncio.run(skill_publication_response(req, service=SkillPublicationService(
        store, Objects(), "test"), deployment="cloud", read_enabled=True,
        manage_enabled=True, **kwargs))


def test_publish_metadata_and_pending_get() -> None:
    store = AsyncMock(spec=SkillPublicationStorePort)
    candidate = _candidate(archive(), SCOPE, "test")
    store.reserve.return_value = candidate
    async def ready(**kwargs: object) -> object:
        return candidate.model_copy(update={"state": "ready", "receipt": kwargs["receipt"]})
    store.mark_ready.side_effect = ready
    response = respond(request(), store)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert store.reserve.call_args.kwargs["idempotency_key"] == "one"
    for private in (b"artifact_ref", b"receipt", b"scope", b"manifest"):
        assert private not in response.body
    store.get.return_value = candidate
    response = respond(request(f"/{candidate.version.skill_id}/versions/"
                               f"{candidate.version.version_id}", "GET"), store)
    assert response.status_code == 200 and b'"state":"publishing"' in response.body


@pytest.mark.parametrize("method,path,status,headers,verified", [
    ("POST", "", 403, None, _verified(scopes=["extensions.read"])),
    ("PUT", "", 405, None, VERIFIED),
    ("GET", "/x/versions/y", 403, None, _verified(scopes=["extensions.manage"])),
    ("POST", "/bad", 404, None, VERIFIED),
    ("POST", "", 415, [(b"content-type", b"text/plain")], VERIFIED),
    ("POST", "", 422, [(b"content-type", b"application/zip")], VERIFIED),
    ("POST", "", 422, [(b"content-type", b"application/zip"),
                        (b"idempotency-key", b"a"), (b"idempotency-key", b"b")], VERIFIED),
])
def test_reject_before_body(method: str, path: str, status: int,
                            headers: object, verified: object) -> None:
    store = AsyncMock(spec=SkillPublicationStorePort)
    receive = AsyncMock(side_effect=AssertionError("must not read body"))
    response = respond(request(path, method, headers=headers, verified=verified,
                               receive=receive), store)
    assert response.status_code == status
    receive.assert_not_called()
    store.reserve.assert_not_called()


def test_oversized_chunks_and_cancellation() -> None:
    store = AsyncMock(spec=SkillPublicationStorePort)
    receive = AsyncMock(return_value={"type": "http.request", "body": b"x" * (10485760 + 1)})
    assert respond(request(receive=receive), store).status_code == 413
    store.reserve.assert_not_called()
    with pytest.raises(asyncio.CancelledError):
        respond(request(receive=AsyncMock(side_effect=asyncio.CancelledError)), store)


def test_forged_scope_detail_is_hidden() -> None:
    store = AsyncMock(spec=SkillPublicationStorePort)
    candidate = _candidate(archive(), SCOPE.model_copy(update={"principal_id": "other"}), "test")
    store.get.return_value = candidate
    response = respond(request(f"/{candidate.version.skill_id}/versions/"
                               f"{candidate.version.version_id}", "GET"), store)
    assert response.status_code == 404


@pytest.mark.parametrize("deployment,read_enabled,manage_enabled,configured", [
    ("local", True, True, True), ("cloud", False, True, True),
    ("cloud", True, False, True), ("cloud", True, True, False),
])
def test_opt_in_gates_do_not_read_body(deployment: str, read_enabled: bool,
                                     manage_enabled: bool, configured: bool) -> None:
    store = AsyncMock(spec=SkillPublicationStorePort)
    receive = AsyncMock(side_effect=AssertionError("must not read body"))
    response = asyncio.run(skill_publication_response(
        request(receive=receive), service=SkillPublicationService(store, Objects(), "test")
        if configured else None, deployment=deployment, read_enabled=read_enabled,
        manage_enabled=manage_enabled,
    ))
    assert response.status_code == 404
    receive.assert_not_called()
    store.reserve.assert_not_called()


def test_timeout_and_invalid_archive_never_reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zebra_agent_api.skill_publications.BODY_TIMEOUT_SECONDS", 0.001)
    store = AsyncMock(spec=SkillPublicationStorePort)
    async def delayed() -> object:
        await asyncio.sleep(1)
        raise AssertionError("timeout must end body read")
    assert respond(request(receive=delayed), store).status_code == 422
    receive = AsyncMock(return_value={"type": "http.request", "body": b"bad zip"})
    assert respond(request(receive=receive), store).status_code == 422
    store.reserve.assert_not_called()


def test_object_failure_leaves_publishing_and_storage_corruption_is_sanitized() -> None:
    store = AsyncMock(spec=SkillPublicationStorePort)
    candidate = _candidate(archive(), SCOPE, "test")
    store.reserve.return_value = candidate
    objects = Objects()
    objects.fail = True
    response = asyncio.run(skill_publication_response(
        request(), service=SkillPublicationService(store, objects, "test"),
        deployment="cloud", read_enabled=True, manage_enabled=True,
    ))
    assert response.status_code == 503
    store.mark_ready.assert_not_called()
    store.get.return_value = candidate.model_copy(update={"state": "ready"})
    response = respond(request(f"/{candidate.version.skill_id}/versions/"
                               f"{candidate.version.version_id}", "GET"), store)
    assert response.status_code == 503
    assert b"receipt" not in response.body


@pytest.mark.parametrize("key", ["", " a", "a b", "x" * 129, "é", "a\n"])
def test_service_key_is_validated_before_zip_or_io(key: str) -> None:
    store = AsyncMock(spec=SkillPublicationStorePort)
    objects = Objects()
    service = SkillPublicationService(store, objects, "test")
    with pytest.raises(ValueError):
        asyncio.run(service.publish(archive=b"bad zip", scope=SCOPE, idempotency_key=key))
    store.reserve.assert_not_called()
    assert objects.calls == 0
