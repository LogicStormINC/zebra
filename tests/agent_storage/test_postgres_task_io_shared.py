"""Explicit address sharing, without global caches or shared connections."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.extensions import ExtensionScope
from agent_core.ports.extensions import ExtensionPageRequest
from agent_storage.postgres import task_io
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.extensions_migration import EXTENSIONS_MIGRATION
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def test_explicit_connector_rejects_different_complete_dsn() -> None:
    dsn = "host=127.0.0.1 dbname=one user=reader sslmode=require password=not-a-secret"
    shared = task_io.TaskIoConnections(dsn)
    first = PostgresDatabase(dsn, deployment_namespace="one", task_io_connections=shared)
    second = PostgresDatabase(dsn, deployment_namespace="two", task_io_connections=shared)
    assert first._task_io is second._task_io is shared
    for different in ("dbname", "user", "sslmode", "password"):
        with pytest.raises(ValueError, match="connection configuration"):
            PostgresDatabase(
                make_conninfo(dsn, **{different: "different"}),
                deployment_namespace="two",
                task_io_connections=shared,
            )


def test_cache_contains_addresses_only_and_refreshes_after_thirty_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def resolve(params: dict[str, Any]) -> list[dict[str, Any]]:
        calls.append(params)
        return [{**params, "hostaddr": "127.0.0.1", "port": "5432"}]

    monkeypatch.setattr(task_io, "conninfo_attempts", resolve)
    shared = task_io.TaskIoConnections("host=127.0.0.1 user=reader password=not-a-secret")
    first = shared._resolve(time.monotonic() + 2)
    assert shared._resolve(time.monotonic() + 2) == first
    assert len(calls) == 1
    assert shared._attempts == ({"host": "127.0.0.1", "hostaddr": "127.0.0.1", "port": "5432"},)
    assert first[0]["user"] == "reader" and first[0]["password"] == "not-a-secret"
    shared._resolved_at -= 31
    assert shared._resolve(time.monotonic() + 2) == first
    assert len(calls) == 2


def test_pg_environment_change_invalidates_address_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def resolve(params: dict[str, Any]) -> list[dict[str, Any]]:
        calls.append(params)
        return [{**params, "hostaddr": "127.0.0.1"}]

    monkeypatch.setattr(task_io, "conninfo_attempts", resolve)
    shared = task_io.TaskIoConnections("host=127.0.0.1")
    shared._resolve(time.monotonic() + 2)
    monkeypatch.setenv("PGOPTIONS", "-c application_name=changed")
    shared._resolve(time.monotonic() + 2)
    assert len(calls) == 2
    shared._resolve(time.monotonic() + 2)
    assert len(calls) == 2


def test_service_configuration_is_never_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    password = ["first"]

    class Child:
        returncode = 0

        def __enter__(self) -> Child:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def communicate(self, value: str, *, timeout: float) -> tuple[str, None]:
            calls.append(json.loads(value))
            return json.dumps(
                [{"host": "service.invalid", "hostaddr": "127.0.0.1", "password": password[0]}]
            ), None

    monkeypatch.setattr(task_io.subprocess, "Popen", lambda *args, **kwargs: Child())
    shared = task_io.TaskIoConnections("service=changing-service")
    assert shared._resolve(time.monotonic() + 2)[0]["password"] == "first"
    password[0] = "changed-service-file"
    assert shared._resolve(time.monotonic() + 2)[0]["password"] == "changed-service-file"
    assert len(calls) == 2 and shared._attempts == ()


def test_shared_connector_keeps_new_connection_and_one_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = task_io.TaskIoConnections("host=127.0.0.1")
    first = PostgresDatabase(
        "host=127.0.0.1", deployment_namespace="one", task_io_connections=shared
    )
    second = PostgresDatabase(
        "host=127.0.0.1", deployment_namespace="two", task_io_connections=shared
    )
    connections = []

    def connect(**kwargs: Any) -> object:
        connections.append((object(), kwargs))
        return connections[-1][0]

    monkeypatch.setattr(shared, "connect", connect)
    deadline = time.monotonic() + 1
    with task_io.task_io_deadline(deadline):
        assert first.connect() is not second.connect()
    assert len(connections) == 2
    assert all(kwargs["deadline"] == deadline for _, kwargs in connections)


def test_all_address_failures_invalidate_shared_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    shared = task_io.TaskIoConnections("host=127.0.0.1")
    shared._resolve(time.monotonic() + 2)
    assert shared._attempts

    def fail(*args: Any, **kwargs: Any) -> None:
        raise psycopg.OperationalError("diagnostic address failure")

    monkeypatch.setattr(task_io.waiting, "wait_conn", fail)
    with pytest.raises(psycopg.OperationalError, match="diagnostic address failure"):
        shared.connect()
    assert shared._attempts == ()


@pytest.fixture
def native_catalog_dsn() -> Iterator[str]:
    configured = os.environ.get("ZEBRA_SHARED_DNS_SCRATCH_DSN")
    if not configured:
        pytest.skip("set ZEBRA_SHARED_DNS_SCRATCH_DSN to an owned isolated QA PostgreSQL")
    params = conninfo_to_dict(configured)
    if not (
        params.get("dbname", "").startswith("zebra-progress-e2e-qa-")
        and params.get("host") in {"127.0.0.1", "localhost"}
    ):
        pytest.fail("shared DNS probe refuses non-scratch configuration")
    schema = "shared_dns_" + uuid4().hex
    with psycopg.connect(configured, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(configured, host="localhost", options=f"-c search_path={schema}")
    try:
        with psycopg.connect(isolated) as connection:
            for statement in EXTENSIONS_MIGRATION.statements:
                connection.execute(statement)
        yield isolated
    finally:
        with psycopg.connect(configured, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_native_cold_catalog_has_one_resolver_and_new_connections_in_one_budget(
    native_catalog_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = task_io.TaskIoConnections(native_catalog_dsn)
    first_store = PostgresDatabase(
        native_catalog_dsn, deployment_namespace="first", task_io_connections=shared
    )
    catalog = PostgresExtensionStore(
        native_catalog_dsn, deployment_namespace="catalog", task_io_connections=shared
    )
    children = []
    spawn = task_io.subprocess.Popen

    def observe(*args: Any, **kwargs: Any) -> Any:
        child = spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(task_io.subprocess, "Popen", observe)
    deadline = time.monotonic() + 2
    scope = ExtensionScope(
        authority_issuer="https://scratch.example",
        namespace_id="catalog",
        principal_id="reader",
        workspace_id="workspace",
    )
    with task_io.task_io_deadline(deadline):
        with first_store.connect() as first:
            first_pid = first.info.backend_pid
            assert first.execute("SELECT 1 AS ready").fetchone() == {"ready": 1}
        page = asyncio.run(catalog.list_skills(scope=scope, page=ExtensionPageRequest(limit=100)))
        with catalog.connect() as second:
            assert second.info.backend_pid != first_pid
            assert second.deadline == first.deadline == deadline
    assert not page.items and len(children) == 1 and first.closed and second.closed
    assert time.monotonic() < deadline


def test_native_service_file_change_is_observed_without_reusing_credentials_or_options(
    native_catalog_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = tmp_path / "pg_service.conf"
    service.touch(mode=0o600)
    params = conninfo_to_dict(native_catalog_dsn)

    def configure(name: str) -> None:
        service.write_text(
            "[changing]\n"
            + "\n".join(
                f"{key}={value}" for key, value in {**params, "application_name": name}.items()
            )
            + "\n"
        )

    monkeypatch.setenv("PGSERVICEFILE", str(service))
    shared = task_io.TaskIoConnections("service=changing")
    store = PostgresDatabase(
        "service=changing", deployment_namespace="service", task_io_connections=shared
    )
    for name in ("before_service_change", "after_service_change"):
        configure(name)
        with store.connect_task_io() as connection:
            assert connection.execute("SHOW application_name").fetchone() == {
                "application_name": name,
            }
        assert shared._attempts == ()
