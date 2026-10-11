"""Cloud media metadata shares admission's remaining observation budget."""

import asyncio
import base64
import os
import select
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from subprocess import Popen
from threading import Event, Thread
from time import monotonic, sleep
from typing import cast
from uuid import UUID, uuid4

import jwt
import psycopg
import pytest
from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
    ArtifactObjectPutRequest,
    ArtifactObjectReceipt,
    ArtifactObjectVerificationStatus,
)
from agent_core.domain.cloud_artifact_requests import (
    ArtifactEventBinding,
    ArtifactFinalizeRequest,
    ArtifactRecordObjectRequest,
    ArtifactReserveRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.host_authority import HostContextEnvelope, HostTechnicalLimits
from agent_core.domain.identifiers import SessionId, TaskId, new_artifact_id
from agent_core.domain.task_bindings import task_bound_host_thread
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_security import PyJwtHostGrantDecoder
from agent_storage import (
    PostgresHostAuthorityStore,
    S3ArtifactObjectStore,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.delivery_audit import PostgresDeliveryAuditStore
from agent_storage.postgres.task_io import TaskIoConnections, current_task_io_deadline
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from starlette.requests import Request
from zebra_agent_api import create_app, create_http_app
from zebra_agent_api.artifact_download import artifact_download_response
from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteAdapter, RouteRequest

from tests.agent_storage.test_artifact_payload_reads import PAYLOAD, ObjectStub
from tests.agent_storage.test_postgres_http_auth_boundary_e2e import (
    HOST_THREAD,
    ORIGIN,
    _claims,
    _registry,
    _StaticResolver,
)
from tests.agent_storage.test_s3_artifact_object_read_bounds import (
    children as _media_children,
)
from tests.agent_storage.test_s3_artifact_object_read_bounds import (
    expectation as _s3_expectation,
)
from tests.agent_storage.test_s3_artifact_object_read_bounds import (
    native_server,
)
from tests.api.test_postgres_host_auth_authorizer import (
    _settings,
)
from tests.api.test_postgres_host_auth_authorizer import (
    dsn as _native_media_dsn,
)
from tests.api.test_postgres_host_auth_authorizer import (
    postgres_dsn as _postgres_dsn,
)
from tests.test_cloud_api_worker_profile_composition import _cloud_settings

postgres_dsn = _postgres_dsn
native_media_dsn = _native_media_dsn
media_children = _media_children


def _request(*, local: bool = False, method: str = "HEAD") -> Request:
    request = Request(
        {
            "type": "http",
            "method": method,
            "path": "/tasks/task-a/artifacts/public-a/preview",
            "headers": [],
            "query_string": b"",
        }
    )
    if not local:
        request.state.host_context = HostContextEnvelope.model_construct(
            scopes=("artifact.read",),
            limits=HostTechnicalLimits(
                max_runtime_seconds=60,
                max_model_tokens=1024,
                max_artifact_bytes=32,
            ),
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )
        request.state.authorization_deadline = monotonic() + 1.0
    return request


class _Adapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float | None]] = []

    def handle(self, request: RouteRequest) -> ApiResponse:
        path = request.path
        self.calls.append((path, current_task_io_deadline()))
        if path.endswith("/artifacts"):
            return ApiResponse(
                200,
                {
                    "artifacts": [
                        {
                            "artifact_id": "run:1",
                            "uri": "artifact://public-a",
                        }
                    ]
                },
            )
        if path.endswith("/content"):
            return ApiResponse(200, {"content_base64": base64.b64encode(b"image").decode()})
        return ApiResponse(
            200,
            {
                "artifact": {
                    "artifact_id": "tool-run:1",
                    "delivery": {
                        "file_name": "image.png",
                        "mime_type": "image/png",
                        "size_bytes": 5,
                    },
                }
            },
        )


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_cloud_metadata_inherits_admission_deadline(method: str) -> None:
    request = _request(method=method)
    adapter = _Adapter()
    response = asyncio.run(artifact_download_response(request, cast(RouteAdapter, adapter)))
    assert response is not None and response.status_code == 200
    assert adapter.calls
    assert all(deadline == request.state.authorization_deadline for _, deadline in adapter.calls)
    assert not any(path.endswith("/artifacts") for path, _ in adapter.calls)


def test_cloud_metadata_does_not_start_after_admission_budget() -> None:
    request = _request()
    request.state.authorization_deadline = monotonic() - 0.01
    adapter = _Adapter()
    response = asyncio.run(artifact_download_response(request, cast(RouteAdapter, adapter)))
    assert response is not None and response.status_code == 503
    assert adapter.calls == []


@pytest.mark.parametrize("expiry", ["missing", None, "invalid", datetime(2026, 10, 3)])
def test_incomplete_host_authority_is_denied_without_read_or_identity_fallback(expiry):
    class MissingScope:
        def require_scope(self, scope):
            assert scope == "artifact.read"
            raise ValueError("missing")

    context = MissingScope()
    if expiry != "missing":
        context.expires_at = expiry
    request = _request(method="GET")
    request.state.host_context = context
    adapter = _Adapter()
    response = asyncio.run(artifact_download_response(request, cast(RouteAdapter, adapter)))
    assert response.status_code == 403
    assert adapter.calls == []


@pytest.mark.parametrize("status", [200, 404, 503])
def test_expired_media_result_is_not_delivered(status: int) -> None:
    request = _request(method="GET")
    request.state.host_context = request.state.host_context.model_copy(
        update={
            "expires_at": datetime.now(UTC) + timedelta(seconds=0.05),
        }
    )

    class SlowContent(_Adapter):
        def handle(self, route: RouteRequest) -> ApiResponse:
            if route.path.endswith("/content"):
                sleep(0.08)
                if status != 200:
                    return ApiResponse(status, {"status": "late_result"})
            return super().handle(route)

    response = asyncio.run(artifact_download_response(request, cast(RouteAdapter, SlowContent())))
    assert response is not None and response.status_code == 403


def test_local_media_reads_keep_existing_unscoped_behavior() -> None:
    adapter = _Adapter()
    response = asyncio.run(
        artifact_download_response(_request(local=True), cast(RouteAdapter, adapter))
    )
    assert response is not None and response.status_code == 200
    assert all(deadline is None for _, deadline in adapter.calls)


def test_cloud_content_inherits_the_same_metadata_deadline() -> None:
    request = _request(method="GET")
    adapter = _Adapter()
    response = asyncio.run(artifact_download_response(request, cast(RouteAdapter, adapter)))
    assert response.status_code == 200
    assert len(adapter.calls) == 2  # One exact detail, then content; no list expansion.
    assert all(deadline == request.state.authorization_deadline for _, deadline in adapter.calls)


def test_cloud_selected_bytes_are_admitted_before_content_read() -> None:
    class Oversized(_Adapter):
        def handle(self, route: RouteRequest) -> ApiResponse:
            response = super().handle(route)
            if "artifact" in response.body:
                response.body["artifact"]["delivery"]["size_bytes"] = 33
            return response

    adapter = Oversized()
    response = asyncio.run(
        artifact_download_response(_request(method="GET"), cast(RouteAdapter, adapter))
    )
    assert response.status_code == 503
    assert not any(path.endswith("/content") for path, _ in adapter.calls)


def test_cloud_encoded_size_is_checked_before_decoder_allocation(monkeypatch) -> None:
    import zebra_agent_api.artifact_download as media

    decoded = []
    original = media.base64.b64decode

    def decode(*args, **kwargs):
        decoded.append(True)
        return original(*args, **kwargs)

    class Oversized(_Adapter):
        def handle(self, route: RouteRequest) -> ApiResponse:
            response = super().handle(route)
            if route.path.endswith("/content"):
                response.body["content_base64"] = base64.b64encode(b"x" * 32).decode()
            return response

    monkeypatch.setattr(media.base64, "b64decode", decode)
    response = asyncio.run(
        artifact_download_response(_request(method="GET"), cast(RouteAdapter, Oversized()))
    )
    assert response.status_code == 503
    assert decoded == []


@pytest.mark.parametrize("cleanup_fault", [False, True])
def test_cancelled_download_collects_native_read_without_replacing_cancel(
    media_children, monkeypatch, cleanup_fault
):
    if cleanup_fault:
        kill = Popen.kill

        def failing_cleanup(child):
            kill(child)
            raise OSError("secondary cleanup")

        monkeypatch.setattr(Popen, "kill", failing_cleanup)
    with native_server("blocked_head") as (store, probe):
        finished = Event()

        class NativeContent(_Adapter):
            def handle(self, route):
                if route.path.endswith("/content"):
                    try:
                        store.verify(_s3_expectation())
                    finally:
                        finished.set()
                return super().handle(route)

        async def cancel():
            task = asyncio.create_task(
                artifact_download_response(
                    _request(method="GET"), cast(RouteAdapter, NativeContent())
                )
            )
            assert await asyncio.to_thread(probe.entered.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert finished.is_set(), "native worker survived API cancellation"
            assert probe.disconnected.wait(0.5)
            assert len(media_children) == 1 and media_children[0].poll() is not None

        asyncio.run(cancel())


@pytest.fixture
def native_objects(request):
    if getattr(request, "param", None) == "native":
        with native_server("normal", PAYLOAD) as (objects, probe):
            yield objects, probe
    elif getattr(request, "param", None) == "minio":
        from tests.agent_storage.test_s3_artifact_objects_minio import _client

        bucket = os.environ.get("ZEBRA_TEST_S3_BUCKET", "")
        if not bucket.startswith("media-read-"):
            pytest.skip("native media requires an explicitly owned scratch MinIO bucket")
        client = _client()
        objects = S3ArtifactObjectStore(client, bucket=bucket)
        try:
            yield objects, None
        finally:
            objects._read_client.close()
            client.close()
    else:
        yield ObjectStub(ArtifactObjectVerificationStatus.VERIFIED), None


@pytest.fixture
def native_media(native_media_dsn, tmp_path, native_objects):
    """Real HTTP, RS256, PG authority/index/lifecycle; only object bytes are a seam."""
    namespace = "native-media-forwarding"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    objects, _ = native_objects
    cloud = replace(
        _cloud_settings(),
        dsn=native_media_dsn,
        deployment_namespace=namespace,
        artifact_objects=objects,
    )
    registry = PostgresHostAuthorityStore(native_media_dsn, deployment_namespace=namespace)
    registry.upsert_registry(_registry(namespace))
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry=registry,
        decoder=PyJwtHostGrantDecoder(_StaticResolver(key.public_key())),
    )
    settings = _settings(native_media_dsn)
    api = create_app(tmp_path / "unused.sqlite", settings=settings, cloud_composition=cloud)

    def headers(*, fault=None):
        claims = _claims(str(uuid4()), namespace, scopes=["agent.run", "artifact.read"])
        if fault == "scope":
            claims["scopes"] = ["agent.run"]
        elif fault == "expired":
            claims["exp"] = int(datetime.now(UTC).timestamp()) - 120
            claims["iat"] = claims["nbf"] = claims["exp"] - 10
        elif fault == "thread":
            claims["resource_refs"] = [
                {**ref, "id": "foreign-thread"} if ref["type"] == "thread" else ref
                for ref in claims["resource_refs"]
            ]
        elif fault == "issuer":
            claims["iss"] = "https://foreign.example.com"
        token = jwt.encode(claims, key, algorithm="RS256")
        return {"Authorization": "Bearer " + token, "Origin": ORIGIN}

    with TestClient(
        create_http_app(
            tmp_path / "unused.sqlite",
            settings=settings,
            cloud_composition=cloud,
            host_grant_authorizer=authorizer,
        )
    ) as client:
        created = client.post(
            "/tasks",
            json={
                "title": "Media",
                "prompt": "Read",
                "workspace": str(tmp_path),
                "execute": False,
                "policy_profile": "full_access",
            },
            headers=headers(),
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["task_id"]
        session_id = SessionId(UUID(task_id))
        binding = api.cloud_control.load_task_binding(TaskId(UUID(task_id)))
        assert task_bound_host_thread(binding, task_id=task_id).resource_id == HOST_THREAD
        assert HOST_THREAD != task_id
        bootstrap_control_plane_epoch(native_media_dsn, deployment_namespace=namespace)
        lease = api.stores.leases.acquire(
            session_id,
            owner_instance_id="native-media-test",
            ttl=timedelta(minutes=5),
        )
        previous = api.stores.events.list_for_session(session_id)[-1].sequence
        reservation = ArtifactReserveRequest(
            artifact_id=new_artifact_id(),
            session_id=session_id,
            intended_event_sequence=previous + 1,
            kind="tool_output",
            mime_type="image/png",
            sha256=sha256(PAYLOAD).hexdigest(),
            size_bytes=len(PAYLOAD),
            idempotency_key="native-media",
            file_name="image.png",
            created_at=datetime.now(UTC),
        )
        artifact_uri = f"artifact://{reservation.artifact_id}"
        authority = WorkerMutationAuthority(
            deployment_namespace=namespace,
            session_id=session_id,
            expected_stream_revision=previous,
            lease_fence=lease.fence,
        )
        metadata = api.stores.artifact_payloads
        metadata.reserve_for_worker(reservation, authority=authority)
        receipt = ArtifactObjectReceipt(
            expectation=ArtifactObjectExpectation(
                deployment_namespace=namespace,
                artifact_id=reservation.artifact_id,
                sha256=reservation.sha256,
                size_bytes=len(PAYLOAD),
            ),
            object_version="v1",
            verified_at=datetime.now(UTC),
        )
        if isinstance(objects, S3ArtifactObjectStore) and native_objects[1] is None:
            receipt = objects.put_if_absent(
                ArtifactObjectPutRequest(expectation=receipt.expectation, payload=PAYLOAD)
            )
        metadata.record_object_for_worker(
            ArtifactRecordObjectRequest(
                artifact_id=reservation.artifact_id,
                session_id=session_id,
                expected_lifecycle_revision=0,
                idempotency_key="native-media-object",
                object_receipt=receipt,
            ),
            authority=authority,
        )
        event = SessionEvent.create(
            session_id=session_id,
            sequence=previous + 1,
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            actor=EventActor.TOOL,
            payload={
                "attempt_number": 1,
                "tool_name": "tests.run",
                "status": "executed",
                "output": "image",
                "metadata": {"artifact_uri": artifact_uri},
            },
        )
        api.stores.events.append(event)
        metadata.finalize_for_worker(
            ArtifactFinalizeRequest(
                artifact_id=reservation.artifact_id,
                session_id=session_id,
                expected_lifecycle_revision=1,
                idempotency_key="native-media-finalize",
                event_binding=ArtifactEventBinding(
                    session_id=session_id,
                    event_id=event.event_id,
                    sequence=event.sequence,
                    artifact_uri=artifact_uri,
                ),
                object_receipt=receipt,
                finalized_at=datetime.now(UTC),
            ),
            authority=authority.model_copy(update={"expected_stream_revision": event.sequence}),
        )
        api.stores.model_tool_projections.replay_session(session_id)
        yield client, headers, task_id, str(reservation.artifact_id), event.sequence, objects


@pytest.mark.parametrize("mode", ["download", "preview", "head"])
def test_native_media_forwards_verified_grant_through_real_routes(native_media, mode):
    client, headers, task_id, public_id, sequence, objects = native_media
    identifier = f"tool-run:{sequence}" if mode == "head" else public_id
    suffix = "download" if mode == "download" else "preview"
    path = f"/tasks/{task_id}/artifacts/{identifier}/{suffix}"
    request_headers = headers()
    if mode == "preview":
        request_headers["Range"] = "bytes=2-5"
    response = client.request("HEAD" if mode == "head" else "GET", path, headers=request_headers)
    assert response.status_code == (206 if mode == "preview" else 200), response.text
    assert response.content == (
        b"" if mode == "head" else PAYLOAD[2:6] if mode == "preview" else PAYLOAD
    )
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert objects.read_count == (1 if mode == "download" else 0)
    assert objects.ranges == ([(2, 5)] if mode == "preview" else [])


@pytest.mark.parametrize(
    "fault,status", [("thread", 404), ("scope", 403), ("expired", 403), ("issuer", 403)]
)
@pytest.mark.parametrize("suffix", ["download", "content"])
def test_native_media_preserves_authority_rejection_before_bytes(
    native_media, fault, status, suffix
):
    client, headers, task_id, public_id, _, objects = native_media
    response = client.get(
        f"/tasks/{task_id}/artifacts/{public_id}/{suffix}", headers=headers(fault=fault)
    )
    assert response.status_code == status
    assert objects.read_count == 0 and objects.ranges == []


@pytest.mark.parametrize("native_objects", ["native"], indirect=True)
@pytest.mark.parametrize("ranged", [False, True])
def test_native_http_pg_and_signed_s3_share_delivery_boundary(
    native_media, native_media_dsn, native_objects, media_children, ranged
):
    client, headers, task_id, public_id, _, _ = native_media
    _, probe = native_objects
    request_headers = headers()
    if ranged:
        request_headers["Range"] = "bytes=2-5"
    response = client.get(
        f"/tasks/{task_id}/artifacts/{public_id}/preview", headers=request_headers
    )
    assert response.status_code == (206 if ranged else 200), response.text
    assert response.content == (PAYLOAD[2:6] if ranged else PAYLOAD)
    assert [method for method, _, _ in probe.requests].count("GET") == 1
    assert probe.requests[-1][2] == ("bytes=2-5" if ranged else None)
    with psycopg.connect(native_media_dsn) as verify:
        assert verify.execute(
            "SELECT count(*) FROM control_plane_delivery_audit_records "
            "WHERE session_id=%s AND action='session.artifact.content'",
            (task_id,),
        ).fetchone() == (1,)
    assert len(media_children) == len(probe.requests)


@pytest.mark.parametrize("suffix", ["download", "content"])
def test_native_http_deferred_audit_commit_is_bounded_and_not_replayed(
    native_media, native_media_dsn, monkeypatch, suffix
):
    client, headers, task_id, public_id, _, objects = native_media
    with psycopg.connect(native_media_dsn) as setup:
        setup.execute("""CREATE FUNCTION media_audit_delay() RETURNS trigger AS $$
          BEGIN IF NEW.action='session.artifact.content' THEN PERFORM pg_sleep(10); END IF;
          RETURN NEW; END; $$ LANGUAGE plpgsql""")
        setup.execute("""CREATE CONSTRAINT TRIGGER media_audit_delay AFTER INSERT
          ON control_plane_delivery_audit_records DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION media_audit_delay()""")
    connections = []
    connect = TaskIoConnections.connect

    def captured(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append((connection, connection.info.backend_pid))
        return connection

    monkeypatch.setattr(TaskIoConnections, "connect", captured)
    started = monotonic()
    response = client.get(f"/tasks/{task_id}/artifacts/{public_id}/{suffix}", headers=headers())
    assert response.status_code == 503
    assert monotonic() - started < 2.5 and objects.read_count == 1
    assert connections and all(connection.closed for connection, _ in connections)
    with psycopg.connect(native_media_dsn, autocommit=True) as verify:
        assert verify.execute(
            "SELECT count(*) FROM control_plane_delivery_audit_records "
            "WHERE session_id=%s AND action='session.artifact.content'",
            (task_id,),
        ).fetchone() == (0,)
        until = monotonic() + 1
        while verify.execute(
            "SELECT 1 FROM pg_stat_activity WHERE pid=ANY(%s)",
            ([pid for _, pid in connections],),
        ).fetchone():
            assert monotonic() < until, "expired audit backend survived cancellation"
            Event().wait(0.01)


@contextmanager
def lost_commit_reply(dsn: str) -> Iterator[tuple[str, Event, list[Thread]]]:
    """Real libpq/PG: drop CommandComplete only after server confirms COMMIT."""
    settings = conninfo_to_dict(dsn)
    committed, stop = Event(), Event()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(2)

        def proxy():
            with (
                listener.accept()[0] as front,
                socket.create_connection(
                    (
                        settings.get("hostaddr", settings.get("host", "127.0.0.1")),
                        int(settings.get("port", 5432)),
                    ),
                    timeout=2,
                ) as back,
            ):
                server_bytes, client_bytes = b"", b""
                while not stop.is_set():
                    for peer in select.select([front, back], [], [], 0.02)[0]:
                        data = peer.recv(65_536)
                        if not data:
                            return
                        if peer is front:
                            client_bytes = (client_bytes + data)[-65_536:]
                            back.sendall(data)
                            continue
                        server_bytes += data
                        while len(server_bytes) >= 5:
                            length = 1 + int.from_bytes(server_bytes[1:5], "big")
                            if len(server_bytes) < length:
                                break
                            frame, server_bytes = server_bytes[:length], server_bytes[length:]
                            if (
                                b"COMMIT\x00" in client_bytes
                                and frame[:1] == b"C"
                                and (frame[5:] == b"COMMIT\x00")
                            ):
                                committed.set()
                                return  # No COMMIT acknowledgment reaches libpq.
                            front.sendall(frame)

        worker = Thread(target=proxy)
        worker.start()
        try:
            yield (
                make_conninfo(
                    dsn,
                    host="127.0.0.1",
                    hostaddr="127.0.0.1",
                    port=listener.getsockname()[1],
                    sslmode="disable",
                ),
                committed,
                [worker],
            )
        finally:
            stop.set()
            worker.join(2)
            assert not worker.is_alive(), "COMMIT fault proxy leaked a socket/thread"


@pytest.mark.parametrize("suffix", ["download", "content"])
def test_native_http_unknown_audit_commit_fails_closed_without_blind_retry(
    native_media, native_media_dsn, monkeypatch, suffix
):
    client, headers, task_id, public_id, _, objects = native_media
    append = PostgresDeliveryAuditStore.append
    attempts = []
    with lost_commit_reply(native_media_dsn) as (proxy_dsn, committed, _):

        def through_proxy(store, record):
            if record.action != "session.artifact.content":
                return append(store, record)
            attempts.append(record)
            original = store._database
            store._database = PostgresDatabase(
                proxy_dsn, deployment_namespace=original.deployment_namespace
            )
            try:
                return append(store, record)
            finally:
                store._database = original

        monkeypatch.setattr(PostgresDeliveryAuditStore, "append", through_proxy)
        response = client.get(f"/tasks/{task_id}/artifacts/{public_id}/{suffix}", headers=headers())
        assert committed.is_set(), "fault did not reach a real durable COMMIT"
        assert response.status_code == 503 and len(attempts) == objects.read_count == 1
    with psycopg.connect(native_media_dsn) as verify:
        assert verify.execute(
            "SELECT count(*) FROM control_plane_delivery_audit_records "
            "WHERE session_id=%s AND action='session.artifact.content'",
            (task_id,),
        ).fetchone() == (1,), "unknown COMMIT was blindly retried"
