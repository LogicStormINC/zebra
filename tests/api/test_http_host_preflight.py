"""HTTP must validate resource targets before consuming a verified Grant."""

import asyncio
from dataclasses import dataclass, field
from dataclasses import replace as dataclass_replace
from datetime import timedelta
from pathlib import Path
from threading import get_ident
from time import monotonic
from types import SimpleNamespace

import httpx
import pytest
from agent_security.host_grant import VerifiedHostGrant
from agent_storage import sqlite_control_plane_stores
from agent_storage.postgres.task_io import current_task_io_deadline
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.requests import Request
from zebra_agent_api import (
    ag_ui_task_view,
    create_http_app,
    extension_management_routes,
    http_host_auth,
)
from zebra_agent_api.http import HostGrantHttpRequest
from zebra_agent_api.http_host_auth import authorize_request
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteAdapter

from tests.api.test_host_auth_http import _cloud_settings, _local_settings
from tests.api.test_task_resource_binding import binding_for, verified
from tests.host_grant_broker.test_grant_broker import _key, _settings

TASK = "11111111-1111-4111-8111-111111111111"


@dataclass
class Authorizer:
    grant: VerifiedHostGrant | None = None
    allowed_origins: tuple[str, ...] = ("https://trench.example.com",)
    calls: list[HostGrantHttpRequest] = field(default_factory=list)
    consumed: list[str] = field(default_factory=list)
    thread_ids: list[int] = field(default_factory=list)

    def authorize(self, request):
        self.calls.append(request)
        self.thread_ids.append(get_ident())
        if self.grant is not None:
            assert request.before_consume is not None
            request.before_consume(self.grant)
            self.consumed.append(request.path)
        return self.grant


def app(tmp_path: Path, authorizer: Authorizer):
    path = tmp_path / "sessions.sqlite"
    return create_http_app(
        path,
        settings=_cloud_settings("postgresql://unused.invalid/zebra"),
        stores=sqlite_control_plane_stores(path),
        host_grant_authorizer=authorizer,
    )


@pytest.fixture(scope="module")
def grant():
    key = _key()
    return verified((key, _settings(key)), run="request-run")


@pytest.mark.parametrize(
    "path",
    [
        "/tasks/bad-uuid",
        "/sessions/bad-uuid",
        "/approvals/bad-uuid",
        "/agui/threads/bad-uuid/runs/request-run/stream",
    ],
)
def test_invalid_target_never_consumes(tmp_path, grant, path):
    authorizer = Authorizer(grant)
    response = TestClient(app(tmp_path, authorizer)).get(
        path, headers={"Authorization": "Bearer verified"}
    )
    assert response.status_code == 400
    assert authorizer.consumed == []


@pytest.mark.parametrize("nested", [False, True])
def test_agui_body_and_path_identity_validate_before_consumption(tmp_path, grant, nested):
    authorizer = Authorizer(grant)
    path = f"/agui/threads/{TASK}/runs/request-run/commands"
    body = {"action": "run", "threadId": TASK, "runId": "request-run", "expectedRevision": 0}
    if nested:
        body["input"] = {"threadId": TASK, "runId": "other-run"}
    else:
        body["threadId"] = "22222222-2222-4222-8222-222222222222"
    response = TestClient(app(tmp_path, authorizer)).post(
        path, json=body, headers={"Authorization": "Bearer verified"}
    )
    assert response.status_code == 400
    assert authorizer.consumed == []


def test_bad_new_task_payload_is_rejected_before_consumption(tmp_path, grant):
    authorizer = Authorizer(grant)
    response = TestClient(app(tmp_path, authorizer)).post(
        "/tasks", json={}, headers={"Authorization": "Bearer verified"}
    )
    assert response.status_code == 400
    assert authorizer.consumed == []


def test_sync_authorizer_runs_outside_event_loop(tmp_path):
    authorizer = Authorizer()
    application = app(tmp_path, authorizer)

    async def request():
        loop_thread = get_ident()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client:
            response = await client.get(
                "/sessions/bad-uuid", headers={"Authorization": "Bearer verified"}
            )
        assert response.status_code == 400
        assert authorizer.thread_ids and authorizer.thread_ids[0] != loop_thread

    asyncio.run(request())


def test_missing_bearer_precedes_body_errors(tmp_path):
    authorizer = Authorizer()
    response = TestClient(app(tmp_path, authorizer)).post("/agui/commands", content="{")
    assert response.status_code == 401
    assert authorizer.calls == []


def request_for(path, *, method="GET", body=b""):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "scheme": "http",
            "path": path,
            "query_string": b"",
            "headers": [(b"authorization", b"Bearer verified")],
            "server": ("test", 80),
        },
        receive,
    )


def authorize(request, api, authorizer):
    return authorize_request(
        request,
        SimpleNamespace(deployment="cloud"),
        api=api,
        host_grant_authorizer=authorizer,
        host_grant_origins=authorizer.allowed_origins,
    )


@pytest.mark.parametrize("mismatch", ["thread", "run", "issuer"])
def test_real_verified_resource_fence_precedes_consumption(grant, mismatch):
    other = grant
    path = f"/agui/threads/{TASK}/runs/request-run/stream"
    if mismatch == "thread":
        from agent_core.domain.host_authority import HostResourceRef

        other = dataclass_replace(
            grant,
            context=grant.context.model_copy(
                update={
                    "resource_refs": tuple(
                        HostResourceRef(type="thread", id="foreign")
                        if ref.resource_type == "thread"
                        else ref
                        for ref in grant.context.resource_refs
                    ),
                }
            ),
        )
    elif mismatch == "run":
        path = f"/agui/threads/{TASK}/runs/foreign/stream"
    else:
        other = dataclass_replace(grant, authority_issuer="https://foreign.test")
    authorizer = Authorizer(other)
    api = SimpleNamespace(
        stores=SimpleNamespace(deployment_namespace="scratch"),
        cloud_control=SimpleNamespace(
            deployment_namespace="scratch",
            load_task_binding=lambda _: binding_for(grant),
        ),
    )
    response = asyncio.run(authorize(request_for(path), api, authorizer))
    assert response.status_code == 404
    assert authorizer.consumed == []


def test_late_wall_clock_authorization_never_reaches_route(grant, monkeypatch):
    class Clock:
        @staticmethod
        def now(zone):
            return grant.context.expires_at + timedelta(seconds=1)

    monkeypatch.setattr(http_host_auth, "datetime", Clock)
    authorizer = Authorizer(grant)
    response = asyncio.run(authorize(request_for("/usage"), None, authorizer))
    assert response.status_code == 403


def test_consumption_unknown_is_not_retryable(monkeypatch):
    from agent_storage.postgres.host_auth import HostGrantConsumptionUnknown

    class UnknownAuthorizer(Authorizer):
        def authorize(self, request):
            raise HostGrantConsumptionUnknown("COMMIT response was lost")

    response = asyncio.run(authorize(request_for("/usage"), None, UnknownAuthorizer()))
    assert response.status_code == 503
    assert b'"retryable":false' in response.body
    assert b"host_grant_consumption_unknown" in response.body


def test_oversized_body_is_rejected_without_authorization(monkeypatch):
    monkeypatch.setattr(http_host_auth, "MAX_HOST_REQUEST_BYTES", 8)
    authorizer = Authorizer()
    response = asyncio.run(
        authorize(
            request_for("/tasks", method="POST", body=b'{"prompt":"too large"}'),
            None,
            authorizer,
        )
    )
    assert response.status_code == 413
    assert authorizer.calls == []


def test_duplicate_json_identity_never_consumes():
    authorizer = Authorizer()
    response = asyncio.run(
        authorize(
            request_for("/agui/commands", method="POST", body=b'{"threadId":"a","threadId":"b"}'),
            None,
            authorizer,
        )
    )
    assert response.status_code == 400
    assert authorizer.calls == []


def test_json_decoding_is_off_the_event_loop(monkeypatch):
    decode = http_host_auth.json.loads
    threads = []

    def tracked(*args, **kwargs):
        threads.append(get_ident())
        return decode(*args, **kwargs)

    monkeypatch.setattr(http_host_auth.json, "loads", tracked)

    async def run():
        loop_thread = get_ident()
        await authorize(request_for("/tasks", method="POST", body=b"{}"), None, Authorizer())
        assert threads and all(thread != loop_thread for thread in threads)

    asyncio.run(run())


def test_nested_json_is_rejected_before_authorization():
    authorizer = Authorizer()
    response = asyncio.run(
        authorize(
            request_for("/tasks", method="POST", body=b"[" * 2000 + b"0" + b"]" * 2000),
            None,
            authorizer,
        )
    )
    assert response.status_code == 400
    assert authorizer.calls == []


def test_slow_json_decoder_does_not_block_other_requests(monkeypatch):
    from threading import Event

    decode = http_host_auth.json.loads
    started, release = Event(), Event()

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(timeout=1)
        return decode(*args, **kwargs)

    monkeypatch.setattr(http_host_auth.json, "loads", delayed)

    async def run():
        decoding = asyncio.create_task(
            authorize(request_for("/tasks", method="POST", body=b"{}"), None, Authorizer())
        )
        try:
            async with asyncio.timeout(0.2):
                while not started.is_set():
                    await asyncio.sleep(0)
                # A second request progresses while the first is still decoding.
                assert await authorize(request_for("/usage"), None, Authorizer()) is None
                assert not decoding.done()
        finally:
            release.set()
            await decoding

    asyncio.run(run())


def test_body_wait_uses_the_authorization_deadline(monkeypatch):
    monkeypatch.setattr(http_host_auth, "HOST_PREFLIGHT_SECONDS", 0.03)
    cancelled = []
    authorizer = Authorizer()

    async def receive():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    request = request_for("/tasks", method="POST")
    request = Request(request.scope, receive)
    response = asyncio.run(authorize(request, None, authorizer))
    assert response.status_code == 503 and cancelled == [True]
    assert authorizer.calls == []
    assert request.state.authorization_deadline < monotonic()


def test_cloud_read_inherits_the_authorization_io_deadline(tmp_path, grant, monkeypatch):
    authorizer = Authorizer(grant)
    observed = []

    def read(self, request):
        observed.append(current_task_io_deadline())
        return ApiResponse(200, {"status": "observed"})

    monkeypatch.setattr(RouteAdapter, "handle", read)
    response = TestClient(app(tmp_path, authorizer)).get(
        "/usage", headers={"Authorization": "Bearer verified"}
    )
    assert response.status_code == 200
    assert observed == [authorizer.calls[0].deadline]


def test_local_read_has_no_cloud_observation_scope(tmp_path, monkeypatch):
    observed = []

    def read(self, request):
        observed.append(current_task_io_deadline())
        return ApiResponse(200, {"status": "local-observed"})

    monkeypatch.setattr(RouteAdapter, "handle", read)
    application = create_http_app(tmp_path / "local.sqlite", settings=_local_settings())
    response = TestClient(application).get("/usage")
    assert response.status_code == 200 and observed == [None]


def test_cloud_read_rejects_a_late_wall_clock_result(tmp_path, grant, monkeypatch):
    now = http_host_auth.datetime.now(http_host_auth.UTC)

    class Clock:
        @staticmethod
        def now(zone):
            return now

    def read(self, request):
        nonlocal now
        now = grant.context.expires_at + timedelta(seconds=1)
        return ApiResponse(200, {"status": "late-success"})

    monkeypatch.setattr(ag_ui_task_view, "datetime", Clock)
    monkeypatch.setattr(RouteAdapter, "handle", read)
    response = TestClient(app(tmp_path, Authorizer(grant))).get(
        "/usage", headers={"Authorization": "Bearer verified"}
    )
    assert response.status_code == 403
    assert response.json()["reason"] == "host_grant_rejected"


@pytest.mark.parametrize("parent_seconds", [1.0, 5.0])
def test_early_extension_read_inherits_remaining_io_budget(
    tmp_path, grant, monkeypatch, parent_seconds
):
    authorizer = Authorizer(grant)
    observed = []

    async def read(request, **kwargs):
        observed.append((current_task_io_deadline(), monotonic()))
        return JSONResponse({"items": []})

    monkeypatch.setattr(http_host_auth, "HOST_CATALOG_READ_SECONDS", parent_seconds)
    monkeypatch.setattr(extension_management_routes, "extension_read_response", read)
    response = TestClient(app(tmp_path, authorizer)).get(
        "/v1/extensions/skill-installations", headers={"Authorization": "Bearer verified"}
    )
    assert response.status_code == 200
    (deadline, at_read), = observed
    assert at_read < deadline <= at_read + 2.0
    parent = authorizer.calls[0].deadline
    assert deadline <= parent
    assert (deadline == parent) is (parent_seconds < 2.0)


def test_early_extension_timeout_cancels_the_async_read(tmp_path, grant, monkeypatch):
    cancelled = []

    async def read(request, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(http_host_auth, "HOST_CATALOG_READ_SECONDS", 0.05)
    monkeypatch.setattr(extension_management_routes, "extension_read_response", read)
    response = TestClient(app(tmp_path, Authorizer(grant))).get(
        "/v1/extensions/skill-installations", headers={"Authorization": "Bearer verified"}
    )
    assert response.status_code == 503 and cancelled == [True]
