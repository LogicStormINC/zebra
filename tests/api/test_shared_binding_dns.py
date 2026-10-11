"""Default signed Host admission and cold binding/SSE use one address cache."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from agent_core.domain.identifiers import TaskId
from agent_storage import PostgresHostAuthorityStore, postgres_composition
from agent_storage.postgres import direct_control, task_io
from zebra_agent_api import http

from tests.agent_security.test_jwks_bounds import jwks_server as _jwks_server
from tests.agent_storage.test_postgres_http_auth_boundary_e2e import (
    HOST_THREAD,
    ORIGIN,
    _claims,
    _http_socket,
    _registry,
)
from tests.api.test_postgres_host_auth_authorizer import _settings
from tests.api.test_shared_dns_composition import native_http_dsn as _native_http_dsn
from tests.test_cloud_api_worker_profile_composition import _cloud_settings

jwks_server = _jwks_server
native_http_dsn = _native_http_dsn


@pytest.mark.parametrize("explicit", [False, True])
def test_binding_reader_retains_one_inert_connector(
    monkeypatch: pytest.MonkeyPatch,
    explicit: bool,
) -> None:
    dsn = "postgresql://unused/bindings"
    shared = task_io.TaskIoConnections(dsn) if explicit else None
    reads = []
    monkeypatch.setattr(
        direct_control,
        "load_task_binding",
        lambda *args, **kwargs: reads.append((args, kwargs)),
    )
    control = direct_control.PostgresDirectControl(
        dsn, deployment_namespace="one", task_io_connections=shared
    )
    task_id = TaskId(uuid4())
    assert control.load_task_binding(task_id) is None
    assert control.load_task_binding(task_id) is None
    connector = control._database._task_io
    assert connector is not None and connector._attempts == ()
    if explicit:
        assert connector is shared
    assert len(reads) == 2
    for args, kwargs in reads:
        assert args == (dsn,)
        assert kwargs == {
            "deployment_namespace": "one",
            "task_id": task_id,
            "task_io_connections": connector,
        }
    with pytest.raises(ValueError, match="connection configuration"):
        direct_control.PostgresDirectControl(
            "postgresql://unused/other",
            deployment_namespace="one",
            task_io_connections=connector,
        )


def test_native_cold_signed_grant_binding_tenant_and_sse_share_one_deadline(
    native_http_dsn: str,
    jwks_server: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    record_property: Callable[[str, object], None],
) -> None:
    uri, key, jwks_calls, _, _ = jwks_server
    namespace = "native-shared-binding"
    record = replace(_registry(namespace), jwks_uri=uri + "/keys")
    registry = PostgresHostAuthorityStore(native_http_dsn, deployment_namespace=namespace)
    registry.upsert_registry(record)
    connectors, connections, backend_pids, children, apis = [], [], [], [], []
    create_connector = postgres_composition.TaskIoConnections
    connect, spawn, create_app = (
        task_io.TaskIoConnections.connect,
        task_io.subprocess.Popen,
        http.create_app,
    )

    def observe_connector(dsn: str) -> task_io.TaskIoConnections:
        shared = create_connector(dsn)
        connectors.append(shared)
        return shared

    def observe_connection(self: task_io.TaskIoConnections, **kwargs: Any) -> Any:
        connection = connect(self, **kwargs)
        connections.append(connection)
        backend_pids.append(connection.info.backend_pid)
        return connection

    def observe_child(*args: Any, **kwargs: Any) -> Any:
        child = spawn(*args, **kwargs)
        if task_io.RESOLVE_SCRIPT in child.args:
            children.append(child)
        return child

    def observe_api(*args: Any, **kwargs: Any) -> Any:
        api = create_app(*args, **kwargs)
        apis.append(api)
        return api

    monkeypatch.setattr(postgres_composition, "TaskIoConnections", observe_connector)
    monkeypatch.setattr(task_io.TaskIoConnections, "connect", observe_connection)
    monkeypatch.setattr(http, "create_app", observe_api)
    cloud = replace(_cloud_settings(), dsn=native_http_dsn, deployment_namespace=namespace)
    app = http.create_http_app(
        tmp_path / "unused.sqlite",
        settings=_settings(native_http_dsn),
        cloud_composition=cloud,
    )
    assert len(connectors) == len(apis) == 1
    shared, api = connectors[0], apis[0]
    assert api.stores.sessions._database._task_io is shared
    assert api.stores.tasks._database._task_io is shared
    assert api.cloud_control._database._task_io is shared

    def headers(claims: dict[str, Any]) -> dict[str, str]:
        return {
            "Authorization": "Bearer "
            + jwt.encode(claims, key, algorithm="RS256", headers={"kid": "current"}),
            "Origin": ORIGIN,
        }

    with _http_socket(app) as base_url, httpx.Client(base_url=base_url, timeout=3) as client:
        created = client.post(
            "/tasks",
            json={
                "title": "Native cold SSE",
                "prompt": "Read",
                "workspace": str(tmp_path),
                "execute": False,
            },
            headers=headers(_claims(str(uuid4()), namespace)),
        )
        assert created.status_code == 201, created.json()
        task_id = created.json()["task_id"]
        binding = api.cloud_control.load_task_binding(TaskId(UUID(task_id)))
        assert binding is not None and task_id != HOST_THREAD
        shared._attempts, shared._resolved_at = (), 0
        connections.clear()
        backend_pids.clear()
        monkeypatch.setattr(task_io.subprocess, "Popen", observe_child)
        claims = _claims("cold-binding-sse", namespace)
        claims["resource_refs"].append({"type": "run", "id": "observed-run"})
        path = f"/agui/threads/{task_id}/runs/observed-run/stream"
        started = monotonic()
        with client.stream("GET", path, headers=headers(claims)) as response:
            elapsed = monotonic() - started
            assert response.status_code == 200, response.read().decode()
            assert response.headers["content-type"].startswith("text/event-stream")
            assert elapsed < 2
            assert len(children) == 1 and all(child.poll() is not None for child in children)
            assert len(connections) >= 7
            assert len(set(backend_pids)) == len(connections)
            assert len({connection.deadline for connection in connections}) == 1
            assert all(connection.closed for connection in connections)
            record_property("cold_sse_headers_seconds", round(elapsed, 6))
            record_property("dns_child_count", len(children))
            record_property("distinct_preflight_connections", len(connections))
        assert jwks_calls == ["/keys"]
        assert api.cloud_control.load_task_binding(TaskId(UUID(task_id))) == binding
        audit = registry.list_audit(issuer=record.issuer, jti="cold-binding-sse")
        assert [item.outcome for item in audit] == ["accepted"]
        assert client.get(path, headers=headers(claims)).status_code == 403
        for fault in ("thread", "run"):
            denied = _claims("wrong-" + fault, namespace)
            if fault == "thread":
                for ref in denied["resource_refs"]:
                    if ref["type"] == "thread":
                        ref["id"] = task_id
            else:
                denied["resource_refs"].append({"type": "run", "id": "foreign-run"})
            rejected = client.get(path, headers=headers(denied))
            assert rejected.status_code == 404, rejected.json()
            assert registry.list_audit(issuer=record.issuer, jti=denied["jti"]) == ()
