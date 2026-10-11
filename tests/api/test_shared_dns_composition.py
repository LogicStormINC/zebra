"""Default catalog composition shares addresses, not authority or connections."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

import httpx
import jwt
import psycopg
import pytest
from agent_core.domain.extensions import ExtensionScope
from agent_storage import (
    PostgresHostAuthorityStore,
    apply_postgres_migrations,
    postgres_composition,
)
from agent_storage.postgres import task_io
from agent_storage.postgres.extensions import PostgresExtensionStore
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from zebra_agent_api import extension_composition, host_auth, http

from tests.agent_security.test_jwks_bounds import jwks_server as _jwks_server
from tests.agent_storage.test_postgres_http_auth_boundary_e2e import _http_socket
from tests.api.test_extension_reads import SKILL
from tests.api.test_postgres_host_auth_authorizer import _claims, _registry, _settings
from tests.test_cloud_api_worker_profile_composition import _cloud_settings

jwks_server = _jwks_server


@pytest.mark.parametrize("override", [False, True])
def test_default_factories_receive_one_connector_without_connecting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, override: bool
) -> None:
    dsn = "postgresql://unused/catalog"
    cloud = replace(_cloud_settings(), dsn="postgresql://override/catalog") if override else None
    active_dsn = cloud.dsn if cloud is not None else dsn
    namespace = cloud.deployment_namespace if cloud is not None else "default"
    from agent_storage import postgres_control_plane_stores

    defaults = cloud or replace(_cloud_settings(), dsn=dsn, deployment_namespace=namespace)
    stores = postgres_control_plane_stores(
        active_dsn,
        deployment_namespace=namespace,
        memory_cursor_signing_key=defaults.memory_cursor_signing_key,
        artifact_objects=defaults.artifact_objects,
        history_scope=defaults.history_scope,
        continuation_scope=defaults.continuation_scope,
    )
    catalogs, authorizers = [], []
    catalog_factory = extension_composition.PostgresExtensionStore
    authorizer_factory = host_auth.build_postgres_host_grant_authorizer

    def catalog(*args: Any, **kwargs: Any) -> PostgresExtensionStore:
        catalogs.append(catalog_factory(*args, **kwargs))
        return catalogs[-1]

    def authorizer(*args: Any, **kwargs: Any) -> Any:
        authorizers.append(authorizer_factory(*args, **kwargs))
        return authorizers[-1]

    monkeypatch.setattr(extension_composition, "PostgresExtensionStore", catalog)
    monkeypatch.setattr(extension_composition, "require_current_schema", lambda dsn: None)
    monkeypatch.setattr(host_auth, "build_postgres_host_grant_authorizer", authorizer)
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: pytest.fail("unexpected DB I/O"))
    http.create_http_app(
        tmp_path / "unused.sqlite",
        settings=replace(_settings(dsn), cloud_extensions_read_enabled=True),
        stores=stores,  # type: ignore[arg-type]
        cloud_composition=cloud,
        host_grant_origins=("https://scratch.example",),
    )
    assert len(catalogs) == len(authorizers) == 1
    shared = catalogs[0]._task_io
    assert isinstance(shared, task_io.TaskIoConnections)
    assert stores.task_io_connections is shared
    assert stores.sessions._database._task_io is shared
    assert authorizers[0].registry._database._task_io is shared
    assert shared._params == conninfo_to_dict(active_dsn)
    assert catalogs[0].deployment_namespace == namespace
    assert authorizers[0].registry.deployment_namespace == namespace


@pytest.fixture
def native_http_dsn() -> Iterator[str]:
    configured = os.environ.get("ZEBRA_SHARED_DNS_SCRATCH_DSN")
    if not configured:
        pytest.skip("set ZEBRA_SHARED_DNS_SCRATCH_DSN to an owned isolated QA PostgreSQL")
    params = conninfo_to_dict(configured)
    if not (
        params.get("dbname", "").startswith("zebra-progress-e2e-qa-")
        and params.get("host") in {"127.0.0.1", "localhost"}
    ):
        pytest.fail("shared DNS HTTP probe refuses non-scratch configuration")
    schema = "shared_catalog_http_" + uuid4().hex
    with psycopg.connect(configured, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(configured, host="localhost", options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(configured, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_native_signed_grant_to_cold_catalog_http_shares_one_budget(
    native_http_dsn: str,
    jwks_server: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    record_property: Callable[[str, object], None],
) -> None:
    uri, key, jwks_calls, _, _ = jwks_server
    namespace = "native-shared-http"
    record = replace(_registry(), jwks_uri=uri + "/keys")
    registry = PostgresHostAuthorityStore(native_http_dsn, deployment_namespace=namespace)
    registry.upsert_registry(record)
    scope = ExtensionScope(
        authority_issuer=record.issuer,
        namespace_id=record.namespace_id,
        principal_id="opaque-subject",
        workspace_id="workspace-a",
    )
    seed = PostgresExtensionStore(native_http_dsn, deployment_namespace=namespace)
    installation = SKILL.model_copy(update={"scope": scope})
    asyncio.run(seed.save_skill(scope=scope, installation=installation, expected_revision=None))
    connectors, connections, backend_pids, children = [], [], [], []
    create_connector = postgres_composition.TaskIoConnections
    connect = task_io.TaskIoConnections.connect
    spawn = task_io.subprocess.Popen

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

    monkeypatch.setattr(postgres_composition, "TaskIoConnections", observe_connector)
    monkeypatch.setattr(task_io.TaskIoConnections, "connect", observe_connection)
    cloud = replace(_cloud_settings(), dsn=native_http_dsn, deployment_namespace=namespace)
    app = http.create_http_app(
        tmp_path / "unused.sqlite",
        settings=replace(_settings(native_http_dsn), cloud_extensions_read_enabled=True),
        cloud_composition=cloud,
    )
    assert len(connectors) == 1
    # CORS startup reads may warm DNS. The measured request must be genuinely cold.
    connectors[0]._attempts = ()
    connectors[0]._resolved_at = 0
    connections.clear()
    backend_pids.clear()
    monkeypatch.setattr(task_io.subprocess, "Popen", observe_child)
    token = jwt.encode(
        _claims("cold-catalog", scopes=["extensions.read"]),
        key,
        algorithm="RS256",
        headers={"kid": "current"},
    )
    headers = {"Authorization": f"Bearer {token}", "Origin": record.allowed_origins[0]}
    with _http_socket(app) as base_url, httpx.Client(base_url=base_url, timeout=2) as client:
        started = monotonic()
        response = client.get("/v1/extensions/skill-installations", headers=headers)
        elapsed = monotonic() - started
        assert response.status_code == 200, response.json()
        assert response.json()["items"][0]["installation_id"] == installation.installation_id
        assert response.json()["next_cursor"] is None
        assert elapsed < 2
        assert len(children) == 1 and jwks_calls == ["/keys"]
        assert len(connections) == 3
        assert len(set(backend_pids)) == len(connections)
        assert len({connection.deadline for connection in connections}) == 1
        assert all(connection.closed for connection in connections)
        record_property("cold_http_seconds", round(elapsed, 6))
        record_property("dns_child_count", len(children))
        record_property("distinct_connection_count", len(connections))
        assert client.get("/v1/extensions/skill-installations", headers=headers).status_code == 403
        foreign = jwt.encode(
            {**_claims("foreign-catalog", scopes=["extensions.read"]), "sub": "foreign-reader"},
            key,
            algorithm="RS256",
            headers={"kid": "current"},
        )
        denied = client.get(
            "/v1/extensions/skill-installations",
            headers={**headers, "Authorization": f"Bearer {foreign}"},
        )
        assert denied.status_code == 200 and denied.json() == {"items": [], "next_cursor": None}
    audit = registry.list_audit(issuer=record.issuer, jti="cold-catalog")
    assert [item.outcome for item in audit] == ["accepted", "replay"]
