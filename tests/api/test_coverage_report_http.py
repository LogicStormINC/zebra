"""Transport regression: no HEAD/range/cache bypass or second Artifact read."""

import asyncio
from hashlib import sha256
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from zebra_agent_api.coverage_report_http import coverage_report_response, report_task_id
from zebra_agent_api.host_auth import _required_scopes_for_request
from zebra_agent_api.http import HTTP_METHODS, HostGrantHttpRequest
from zebra_agent_api.responses import ApiResponse

from tests.api.test_coverage_http_admission import grant

TASK = "11111111-1111-1111-1111-111111111111"
PATH = f"/tasks/{TASK}/coverage/report"
BODY = b'{"observations":[],"schema":"coverage-report/1"}'


def request(method="GET", headers=(), verified=True):
    result = Request({
        "type": "http", "method": method, "scheme": "http", "server": ("test", 80),
        "path": PATH, "query_string": b"", "headers": list(headers),
    })
    if verified:
        result.state.verified_host_grant = grant()
        result.state.host_context = result.state.verified_host_grant.context
    return result


def compose(monkeypatch, result=None, error=None):
    calls = []

    def read(api, task_id, verified):
        calls.append((task_id, verified))
        if error:
            raise error
        return result

    monkeypatch.setattr("zebra_agent_api.coverage_report_read.read_coverage_report", read)
    monkeypatch.setattr(
        "zebra_agent_api.coverage_report_http.tenant_scope_response", lambda *_: None
    )
    return SimpleNamespace(app=object()), calls


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_certified_bytes_and_head_use_one_full_gate(monkeypatch, method):
    digest = sha256(BODY).hexdigest()
    adapter, calls = compose(monkeypatch, (SimpleNamespace(report_digest=digest), "ref", BODY))
    response = asyncio.run(coverage_report_response(
        request(method, [(b"if-none-match", f'"{digest}"'.encode())]), adapter
    ))
    assert response.status_code == 200 and len(calls) == 1
    assert response.body == (BODY if method == "GET" else b"")
    assert response.headers["content-length"] == str(len(BODY))
    assert response.headers["x-coverage-report-sha256"] == digest
    assert response.headers["etag"] == f'"{digest}"'
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-type"] == "application/json"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_ranges_cannot_bypass_certificate_or_authority(monkeypatch, method):
    adapter, calls = compose(monkeypatch, (SimpleNamespace(report_digest="a" * 64), "ref", BODY))
    response = asyncio.run(coverage_report_response(
        request(method, [(b"range", b"bytes=0-1")]), adapter
    ))
    assert response.status_code == 416 and len(calls) == 1
    adapter, calls = compose(monkeypatch, error=PermissionError("private credential"))
    response = asyncio.run(coverage_report_response(
        request(method, [(b"range", b"bytes=0-1")]), adapter
    ))
    assert response.status_code == 403 and b"private credential" not in response.body


@pytest.mark.parametrize(("error", "status"), [
    (None, 409), (ValueError("private proof"), 409),
    (PermissionError("private authority"), 403), (RuntimeError("private DSN"), 503),
])
def test_refused_reads_are_private_and_never_return_bytes(monkeypatch, error, status):
    adapter, calls = compose(monkeypatch, error=error)
    response = asyncio.run(coverage_report_response(request(), adapter))
    assert len(calls) == 1 and response.status_code == status
    assert BODY not in response.body and b"private DSN" not in response.body
    assert response.headers["cache-control"] == "private, no-store"


def test_signed_grant_and_tenant_checks_precede_report_io(monkeypatch):
    adapter, calls = compose(monkeypatch)
    response = asyncio.run(coverage_report_response(request(verified=False), adapter))
    assert response.status_code == 403 and not calls
    monkeypatch.setattr(
        "zebra_agent_api.coverage_report_http.tenant_scope_response",
        lambda *_: ApiResponse(404, {"status": "not_found"}),
    )
    response = asyncio.run(coverage_report_response(request(), adapter))
    assert response.status_code == 404 and not calls


def test_exact_route_and_read_only_grant_scopes():
    assert "HEAD" in HTTP_METHODS
    for method in ("GET", "HEAD"):
        assert _required_scopes_for_request(
            HostGrantHttpRequest(method, PATH, None, "Bearer token")
        ) == ("history.read", "artifact.read")
    assert report_task_id(PATH) == TASK
    for path in (PATH + "/extra", PATH.replace(TASK, "invalid"), "/sessions/" + TASK):
        assert report_task_id(path) is None
    assert _required_scopes_for_request(
        HostGrantHttpRequest("POST", PATH, None, "Bearer token")
    ) == ()


def test_registered_http_routes_authorize_once_per_request(tmp_path, monkeypatch):
    from agent_storage import sqlite_control_plane_stores
    from fastapi.testclient import TestClient
    from zebra_agent_api import create_http_app

    from tests.api.test_host_auth_http import _cloud_settings

    authorizations = []

    class Authorizer:
        allowed_origins = ("https://trench.example.com",)

        def authorize(self, http_request):
            authorizations.append(http_request)
            return grant()

    digest = sha256(BODY).hexdigest()
    _, reads = compose(monkeypatch, (SimpleNamespace(report_digest=digest), "ref", BODY))
    path = tmp_path / "http.sqlite"
    client = TestClient(create_http_app(
        path, settings=_cloud_settings("postgresql://unused"),
        stores=sqlite_control_plane_stores(path), host_grant_authorizer=Authorizer(),
    ))
    assert client.get(PATH).status_code == 401
    assert not reads and not authorizations
    for method in ("GET", "HEAD"):
        response = client.request(method, PATH, headers={
            "Authorization": "Bearer signed", "Origin": "https://trench.example.com",
        })
        assert response.status_code == 200
        assert response.content == (BODY if method == "GET" else b"")
        assert "X-Coverage-Report-Sha256" in response.headers["access-control-expose-headers"]
    assert [item.method for item in authorizations] == ["GET", "HEAD"]
    assert len(reads) == 2
