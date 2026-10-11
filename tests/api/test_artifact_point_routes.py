"""Production route point reads must not expand the whole Artifact list."""

import asyncio
import base64
from threading import Event
from time import monotonic

import httpx
import pytest
from agent_storage import (
    PostgresSessionArtifactReadStore,
    SQLiteArtifactStore,
    SQLiteDeliveryAuditStore,
)
from agent_storage.artifact_object_reads import artifact_read_scope
from agent_storage.postgres.task_io import TaskIoConnections, current_task_io_deadline
from fastapi.testclient import TestClient
from starlette.requests import Request
from zebra_agent_api import create_http_app
from zebra_agent_api.app import create_app
from zebra_agent_api.artifact_download import authorized_artifact_read
from zebra_agent_api.routes import RouteRequest

from tests.agent_storage.test_artifact_payload_reads import PAYLOAD
from tests.agent_storage.test_s3_artifact_object_read_bounds import native_server
from tests.api.session_artifacts.session_artifact_support import (
    _seed_payload_backed_tool_artifact,
    _seed_session,
    _seed_workspace_policy,
    _settings,
)
from tests.api.test_artifact_download_deadline import (
    media_children as _media_children,
)
from tests.api.test_artifact_download_deadline import (
    native_media as _native_media,
)
from tests.api.test_artifact_download_deadline import (
    native_media_dsn as _native_media_dsn,
)
from tests.api.test_artifact_download_deadline import (
    native_objects as _native_objects,
)
from tests.api.test_artifact_download_deadline import (
    postgres_dsn as _postgres_dsn,
)

native_media = _native_media
native_media_dsn = _native_media_dsn
native_objects = _native_objects
postgres_dsn = _postgres_dsn
media_children = _media_children


def no_listing(*args, **kwargs):
    raise AssertionError("single Artifact route called list_for_session")


def test_observation_scope_cannot_wrap_prune_or_retry_mutation():
    class NoMutation:
        def handle(self, route):
            raise AssertionError("observation scope reached a mutation")

    path = "/tasks/task/artifacts/tool-run:1/prune"
    request = Request({"type": "http", "method": "POST", "path": path, "headers": []})
    response = asyncio.run(
        authorized_artifact_read(
            request,
            NoMutation(),
            RouteRequest(method="POST", path=path),
        )
    )
    assert response.status_code == 405


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("action", ["detail", "content", "prune"])
def test_native_sqlite_adapter_reads_one_artifact(tmp_path, monkeypatch, public, action):
    path = tmp_path / "points.sqlite"
    session = _seed_session(path)
    payload = _seed_payload_backed_tool_artifact(path, session.session_id)
    api = create_app(path)
    monkeypatch.setattr(SQLiteArtifactStore, "list_for_session", no_listing)
    identifier = str(payload.artifact_id) if public else "tool-run:5"
    if action == "prune":
        response = api.prune_session_artifact(str(session.session_id), identifier)
    else:
        read = (
            api.get_session_artifact_detail
            if action == "detail"
            else api.get_session_artifact_content
        )
        response = read(str(session.session_id), identifier)
    assert response.status_code == 200, response.body
    if action == "content":
        assert base64.b64decode(response.body["content_base64"]) == b"pytest passed"
        assert response.body["artifact_id"] == "tool-run:5"
    audit = SQLiteDeliveryAuditStore(path).list_for_session(session.session_id)
    assert audit[-1].result_metadata["artifact_id"] == "tool-run:5"
    assert audit[-1].action == f"session.artifact.{action}"


@pytest.mark.parametrize("mode", ["download", "preview", "head"])
def test_native_sqlite_http_public_id_does_not_list(tmp_path, monkeypatch, mode):
    path = tmp_path / "points.sqlite"
    session = _seed_session(path)
    payload = _seed_payload_backed_tool_artifact(
        path,
        session.session_id,
        mime_type="image/png",
        payload=b"image",
        file_name="image.png",
    )
    _seed_workspace_policy(path, session.session_id, "full_access")
    app = create_http_app(path, settings=_settings(None))
    monkeypatch.setattr(SQLiteArtifactStore, "list_for_session", no_listing)
    with TestClient(app) as client:
        suffix = "download" if mode == "download" else "preview"
        response = client.request(
            "HEAD" if mode == "head" else "GET",
            f"/tasks/{session.session_id}/artifacts/{payload.artifact_id}/{suffix}",
        )
    assert response.status_code == 200, response.text
    assert response.content == (b"" if mode == "head" else b"image")
    assert response.headers["etag"] == '"tool-run:5"'


@pytest.mark.parametrize("native_objects", ["native"], indirect=True)
@pytest.mark.parametrize("mode", ["detail", "content", "download", "preview", "head"])
def test_native_pg_http_public_point_never_lists_or_reads_other_objects(
    native_media, native_objects, media_children, monkeypatch, mode
):
    client, headers, task_id, public_id, sequence, _ = native_media
    _, probe = native_objects
    monkeypatch.setattr(PostgresSessionArtifactReadStore, "list_for_session", no_listing)
    suffix = "" if mode == "detail" else "/preview" if mode == "head" else f"/{mode}"
    response = client.request(
        "HEAD" if mode == "head" else "GET",
        f"/tasks/{task_id}/artifacts/{public_id}{suffix}",
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    if mode == "detail":
        assert response.json()["artifact"]["artifact_id"] == f"tool-run:{sequence}"
    elif mode == "content":
        assert base64.b64decode(response.json()["content_base64"]) == PAYLOAD
    else:
        assert response.content == (b"" if mode == "head" else PAYLOAD)
    assert probe.requests
    assert all(public_id in path for _, path, _ in probe.requests)
    assert sum(method == "GET" for method, _, _ in probe.requests) == (
        1 if mode in {"content", "download", "preview"} else 0
    )


def test_point_keeps_sensitive_fact_outside_preview_and_foreign_session_denial(
    tmp_path, monkeypatch
):
    path = tmp_path / "points.sqlite"
    session, foreign = _seed_session(path), _seed_session(path)
    payload = _seed_payload_backed_tool_artifact(
        path,
        session.session_id,
        output="x" * 200 + " token=secret",
    )
    api = create_app(path)
    monkeypatch.setattr(SQLiteArtifactStore, "list_for_session", no_listing)
    assert (
        api.get_session_artifact_detail(
            str(session.session_id), str(payload.artifact_id)
        ).status_code
        == 409
    )
    assert (
        api.get_session_artifact_content(
            str(foreign.session_id), str(payload.artifact_id)
        ).status_code
        == 404
    )
    assert (
        api.prune_session_artifact(str(foreign.session_id), str(payload.artifact_id)).status_code
        == 404
    )
    audit = SQLiteDeliveryAuditStore(path).list_for_session(session.session_id)
    assert audit[-1].result_metadata["access_class"] == "sensitive"


def test_shared_content_admits_bytes_before_any_payload_reader(tmp_path, monkeypatch):
    path = tmp_path / "points.sqlite"
    session = _seed_session(path)
    payload = _seed_payload_backed_tool_artifact(path, session.session_id)
    api = create_app(path)

    def body(*args, **kwargs):
        raise AssertionError("payload reader started before byte admission")

    monkeypatch.setattr(api.stores.artifact_payload_reader, "read_payload_bytes", body)
    with artifact_read_scope(max_bytes=1):
        response = api.get_session_artifact_content(
            str(session.session_id), str(payload.artifact_id)
        )
    assert response.status_code == 409
    assert response.body["reason"] == "artifact_byte_limit_exceeded"
    audit = SQLiteDeliveryAuditStore(path).list_for_session(session.session_id)
    assert audit[-1].action == "session.artifact.content"
    assert audit[-1].result_metadata["artifact_id"] == "tool-run:5"


@pytest.mark.parametrize("resource", ["tasks", "sessions"])
def test_native_json_content_obeys_verified_host_artifact_byte_limit(
    native_media, monkeypatch, resource
):
    import tests.api.test_artifact_download_deadline as fixtures

    client, headers, task_id, public_id, _, objects = native_media
    claims = fixtures._claims

    def bounded_claims(*args, **kwargs):
        result = claims(*args, **kwargs)
        result["limits"]["max_artifact_bytes"] = 1
        return result

    monkeypatch.setattr(fixtures, "_claims", bounded_claims)
    response = client.get(f"/{resource}/{task_id}/artifacts/{public_id}/content", headers=headers())
    assert response.status_code in {409, 503}, response.text
    assert objects.read_count == 0, "verified Host byte limit was checked after body allocation"
    assert "content_base64" not in response.json()


@pytest.mark.parametrize("resource", ["tasks", "sessions"])
@pytest.mark.parametrize("mode", ["blocked_head", "blocked_get"])
def test_native_json_cancel_collects_actual_socket_and_child_before_return(
    native_media, media_children, monkeypatch, resource, mode
):
    client, headers, task_id, public_id, _, objects = native_media
    with native_server(mode, PAYLOAD) as (blocked, probe):
        finished = Event()
        operation = "verify" if mode == "blocked_head" else "read_version_verified"

        def read(*args):
            try:
                return getattr(blocked, operation)(*args)
            finally:
                finished.set()

        monkeypatch.setattr(objects, operation, read)

        async def cancelled_request():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
            ) as actual:
                request = asyncio.create_task(
                    actual.get(
                        f"/{resource}/{task_id}/artifacts/{public_id}/content",
                        headers=headers(),
                    )
                )
                assert await asyncio.to_thread(probe.entered.wait, 1)
                started = monotonic()
                request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await request
                assert finished.is_set(), "JSON read thread survived cancellation return"
                assert probe.disconnected.wait(0.5), "JSON read socket survived cancellation"
                assert monotonic() - started < 0.7
                assert media_children and all(child.poll() is not None for child in media_children)

        try:
            asyncio.run(cancelled_request())
        finally:
            # Even a RED must collect its own fixture's bounded leftover worker.
            assert finished.wait(3)


@pytest.mark.parametrize("native_objects", ["native"], indirect=True)
@pytest.mark.parametrize("limit", [3, 4])
def test_native_json_range_admits_selected_bytes_and_audits_once(
    native_media, native_media_dsn, native_objects, monkeypatch, limit
):
    import psycopg

    import tests.api.test_artifact_download_deadline as fixtures

    client, headers, task_id, public_id, sequence, _ = native_media
    _, probe = native_objects
    claims = fixtures._claims
    connections = []
    connect = TaskIoConnections.connect

    def captured(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append((connection, current_task_io_deadline()))
        return connection

    def bounded_claims(*args, **kwargs):
        result = claims(*args, **kwargs)
        result["limits"]["max_artifact_bytes"] = limit
        return result

    monkeypatch.setattr(fixtures, "_claims", bounded_claims)
    monkeypatch.setattr(TaskIoConnections, "connect", captured)
    response = client.get(
        f"/tasks/{task_id}/artifacts/{public_id}/content",
        params={"range_start": "2", "range_end": "5"},
        headers=headers(),
    )
    if limit == 3:
        assert response.status_code == 409, response.text
        assert response.json()["reason"] == "artifact_byte_limit_exceeded"
        assert not any(method == "GET" for method, _, _ in probe.requests)
    else:
        assert response.status_code == 200, response.text
        assert response.json()["artifact_id"] == f"tool-run:{sequence}"
        assert response.json()["size_bytes"] == 4
        assert base64.b64decode(response.json()["content_base64"]) == PAYLOAD[2:6]
        assert [method for method, _, _ in probe.requests].count("GET") == 1
        assert probe.requests[-1][2] == "bytes=2-5"
    assert connections and connections[0][1] is not None
    deadline = connections[0][1]
    assert all(
        connection.closed and connection.deadline == scoped == deadline
        for connection, scoped in connections
    ), "admission, source reads and audit did not share one actual I/O deadline"
    with psycopg.connect(native_media_dsn) as verify:
        assert verify.execute(
            "SELECT count(*) FROM control_plane_delivery_audit_records "
            "WHERE session_id=%s AND action='session.artifact.content'",
            (task_id,),
        ).fetchone() == (1,)


@pytest.mark.parametrize("native_objects", ["minio"], indirect=True)
@pytest.mark.parametrize(
    "mode", ["detail", "content", "download", "preview", "head", "json_range", "preview_range"]
)
def test_native_minio_current_host_point_reads_preserve_full_bytes_and_ranges(
    native_media, native_media_dsn, native_objects, media_children, monkeypatch, mode
):
    import psycopg

    client, headers, task_id, public_id, sequence, objects = native_media
    monkeypatch.setattr(PostgresSessionArtifactReadStore, "list_for_session", no_listing)
    suffix = (
        ""
        if mode == "detail"
        else "/content"
        if mode == "json_range"
        else "/preview"
        if mode in {"head", "preview_range"}
        else f"/{mode}"
    )
    request_headers = headers()
    if mode == "preview_range":
        request_headers["Range"] = "bytes=2-5"
    response = client.request(
        "HEAD" if mode == "head" else "GET",
        f"/tasks/{task_id}/artifacts/{public_id}{suffix}",
        headers=request_headers,
        params={"range_start": "2", "range_end": "5"} if mode == "json_range" else None,
    )
    assert response.status_code == (206 if mode == "preview_range" else 200), response.text
    expected = PAYLOAD[2:6] if mode in {"json_range", "preview_range"} else PAYLOAD
    if mode == "detail":
        assert response.json()["artifact"]["artifact_id"] == f"tool-run:{sequence}"
    elif mode in {"content", "json_range"}:
        assert response.json()["artifact_id"] == f"tool-run:{sequence}"
        assert base64.b64decode(response.json()["content_base64"]) == expected
        assert response.json()["size_bytes"] == len(expected)
    else:
        assert response.content == (b"" if mode == "head" else expected)
        assert response.headers["etag"] == f'"tool-run:{sequence}"'
    with psycopg.connect(native_media_dsn) as verify:
        assert verify.execute(
            "SELECT count(*) FROM control_plane_delivery_audit_records "
            "WHERE session_id=%s AND action='session.artifact.content'",
            (task_id,),
        ).fetchone() == (0 if mode in {"detail", "head"} else 1,)
    assert objects._native_reads is True
    assert media_children and all(child.poll() is not None for child in media_children)
