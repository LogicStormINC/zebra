from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from agent_storage import apply_postgres_migrations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.host_registry_config import load_host_management_config
from zebra_agent_api.host_registry_management import register_host_registry_management
from zebra_agent_config import ZebraAgentSettings, load_settings

TOKEN = "rthm_" + "a" * 43
PATH = "/management/v1/host-registry"
HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "X-Runtime-Deployment": "runtime-a",
    "X-Runtime-Audience": "management-a",
    "X-Runtime-Product": "a",
    "X-Runtime-Environment": "dev",
    "X-Runtime-Trust-Revision": "1",
}


def config() -> dict[str, object]:
    return {
        "deploymentId": "runtime-a",
        "deploymentNamespace": "isolated",
        "audience": "management-a",
        "productId": "a",
        "environment": "dev",
        "trustRevision": 1,
        "credentialSha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
        "expiresAt": "2099-01-01T00:00:00Z",
        "actions": ["host-registry.read", "host-registry.write"],
        "registry": {
            "hostAppId": "host-a",
            "namespaceId": "tenant-a",
            "issuer": "https://broker.example",
            "audience": "agent-a",
            "jwksUri": "https://broker.example/jwks",
            "allowedOrigins": ["https://ui.example"],
            "algorithms": ["RS256"],
            "policyVersion": "v1",
            "active": True,
        },
    }


def write(path: Path, value: dict[str, object]) -> None:
    tmp = path.with_suffix(".new")
    tmp.write_text(json.dumps(value))
    tmp.chmod(0o600)
    tmp.replace(path)


@pytest.fixture(scope="module")
def isolated_dsn() -> Iterator[str]:
    container = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "-e",
            "POSTGRES_PASSWORD=isolated-host-api",
            "-p",
            "127.0.0.1::5432",
            "postgres:17-alpine",
        ],
        text=True,
    ).strip()
    try:
        address = subprocess.check_output(
            ["docker", "port", container, "5432/tcp"], text=True
        ).strip()
        for _ in range(150):
            ready = subprocess.run(
                ["docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"],
                capture_output=True,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("owned test PostgreSQL not ready")
        dsn = f"postgres://postgres:isolated-host-api@{address}/postgres?sslmode=disable"
        apply_postgres_migrations(dsn)
        yield dsn
    finally:
        subprocess.run(["docker", "rm", "-fv", container], check=True, capture_output=True)


@pytest.fixture
def prepared(tmp_path: Path, isolated_dsn: str) -> tuple[Path, ZebraAgentSettings]:
    from agent_storage.postgres.host_management import HostManagementStore

    value = config()
    value["deploymentNamespace"] = "api-" + uuid4().hex
    path = tmp_path / "management.json"
    write(path, value)
    namespace = str(value["deploymentNamespace"])
    approved = load_host_management_config(str(path), namespace)
    HostManagementStore(isolated_dsn, deployment_namespace=namespace).approve(approved.trust, 0)
    settings = replace(
        load_settings({}), database_url=isolated_dsn, host_management_config=str(path)
    )
    return path, settings


def client_for(path: Path, settings: ZebraAgentSettings) -> TestClient:
    namespace = str(json.loads(path.read_text())["deploymentNamespace"])
    app = FastAPI()
    register_host_registry_management(app, settings, namespace)
    return TestClient(app)


def test_current_registry_cas_receipt_and_shared_rotation(
    prepared: tuple[Path, ZebraAgentSettings],
) -> None:
    from agent_storage.postgres.host_management import HostManagementStore

    path, settings = prepared
    request = {"expectedRevision": 0, "operationId": str(uuid4()), "active": True}
    with client_for(path, settings) as one, client_for(path, settings) as two:
        assert one.get(PATH, headers=HEADERS).json()["revision"] == 0
        result = one.put(PATH, headers=HEADERS, json=request)
        assert result.status_code == 200 and result.json()["revision"] == 1
        replay = two.put(PATH, headers=HEADERS, json=request)
        assert replay.status_code == 200 and replay.json()["replayed"]
        assert two.put(PATH, headers=HEADERS, json={**request, "active": False}).status_code == 409
        disable = {"expectedRevision": 1, "operationId": str(uuid4()), "active": False}
        assert two.put(PATH, headers=HEADERS, json=disable).json()["revision"] == 2
        assert one.get(PATH, headers=HEADERS).json()["registry"]["active"] is False
        current = load_host_management_config(
            str(path), str(json.loads(path.read_text())["deploymentNamespace"])
        )
        revoked = replace(current.trust, revision=2, fingerprint="b" * 64)
        HostManagementStore(
            settings.database_url,
            deployment_namespace=str(json.loads(path.read_text())["deploymentNamespace"]),
        ).approve(revoked, 1)
        assert one.get(PATH, headers=HEADERS).status_code == 503
        assert two.put(PATH, headers=HEADERS, json=request).status_code == 503


def test_strict_http_boundaries(prepared: tuple[Path, ZebraAgentSettings]) -> None:
    path, settings = prepared
    body = {"expectedRevision": 0, "operationId": str(uuid4()), "active": True}
    with client_for(path, settings) as client:
        for token in ("rtmg_" + "a" * 43, "operator", "od_access_" + "a" * 43, TOKEN[:-1] + "b"):
            assert (
                client.get(
                    PATH, headers={**HEADERS, "Authorization": "Bearer " + token}
                ).status_code
                == 401
            )
        assert (
            client.get(
                PATH, headers=[*HEADERS.items(), ("Authorization", "Bearer " + TOKEN)]
            ).status_code
            == 401
        )
        assert (
            client.get(PATH, headers=[*HEADERS.items(), ("X-Runtime-Product", "a")]).status_code
            == 403
        )
        assert client.get(PATH, headers={**HEADERS, "X-Runtime-Product": "b"}).status_code == 403
        assert client.get(PATH + "?x=y", headers=HEADERS).status_code == 400
        assert client.get(PATH, headers={**HEADERS, "Cookie": "session=a"}).status_code == 400
        assert client.request("GET", PATH, headers=HEADERS, content="{}").status_code == 400
        assert client.post(PATH, headers=HEADERS, json=body).status_code == 405
        for invalid in (
            {},
            {**body, "scope": "other"},
            {**body, "expectedRevision": True},
            {**body, "expectedRevision": -1},
            {**body, "active": None},
            {**body, "operationId": "not-uuid"},
        ):
            assert client.put(PATH, headers=HEADERS, json=invalid).status_code == 400
        assert (
            client.put(
                PATH,
                headers={**HEADERS, "Content-Type": "application/json"},
                content='{"active":true,"active":false}',
            ).status_code
            == 400
        )
        assert (
            client.put(
                PATH, headers={**HEADERS, "Content-Type": "application/json"}, content="x" * 16385
            ).status_code
            == 400
        )
        assert (
            client.put(
                PATH, headers={**HEADERS, "Content-Type": "text/plain"}, content=json.dumps(body)
            ).status_code
            == 400
        )
        response = client.get(PATH, headers=HEADERS)
        assert response.headers["cache-control"] == "no-store"
        assert TOKEN not in response.text and "credentialSha256" not in response.text


@pytest.mark.parametrize(
    "mutation",
    [
        {"actions": ["target.describe"]},
        {"actions": ["host-registry.read", "host-registry.read"]},
        {"trustRevision": True},
        {"credentialSha256": "bad"},
        {"expiresAt": "2099-01-01T00:00:00+08:00"},
        {"unknown": 1},
        {"registry": {}},
        {"deploymentNamespace": "wrong"},
    ],
)
def test_strict_config(tmp_path: Path, mutation: dict[str, object]) -> None:
    path = tmp_path / "config.json"
    write(path, {**config(), **mutation})
    with pytest.raises((ValueError, TypeError, KeyError)):
        load_host_management_config(str(path), "isolated")


def test_private_config_and_disabled_actions(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    write(path, {**config(), "actions": []})
    assert not load_host_management_config(str(path), "isolated").actions
    path.chmod(0o644)
    with pytest.raises(ValueError):
        load_host_management_config(str(path), "isolated")
    write(path, config())
    path.write_text('{"x":1,"x":2}')
    with pytest.raises(ValueError):
        load_host_management_config(str(path), "isolated")
    with pytest.raises(ValueError):
        load_host_management_config("relative.json", "isolated")


def test_empty_actions_and_expired_config_deny(prepared: tuple[Path, ZebraAgentSettings]) -> None:
    path, settings = prepared
    value = json.loads(path.read_text())
    value["actions"] = []
    write(path, value)
    with client_for(path, settings) as client:
        assert client.get(PATH, headers=HEADERS).status_code == 403
    value["actions"] = ["host-registry.read"]
    value["expiresAt"] = "2000-01-01T00:00:00Z"
    write(path, value)
    with client_for(path, settings) as client:
        assert client.get(PATH, headers=HEADERS).status_code == 403


def test_disabled_default_does_not_force_execution_stores(tmp_path: Path) -> None:
    settings = load_settings({})
    assert settings.host_management_config is None
    app = create_http_app(tmp_path / "local.sqlite", settings=settings)
    with TestClient(app) as client:
        assert client.get(PATH, headers=HEADERS).status_code == 503
    assert (
        load_settings(
            {"ZEBRA_HOST_REGISTRY_MANAGEMENT_CONFIG": "/private/test.json"}
        ).host_management_config
        == "/private/test.json"
    )


def test_timeout_keeps_actual_worker_capacity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import zebra_agent_api.host_registry_management as transport

    done = threading.Event()
    entered = threading.Event()

    def blocked(*args: object) -> object:
        entered.set()
        done.wait(2)
        raise ValueError("private config path")

    monkeypatch.setattr(transport, "load_host_management_config", blocked)
    monkeypatch.setattr(transport, "REQUEST_TIMEOUT", 0.03)
    app = FastAPI()
    register_host_registry_management(app, load_settings({}), "isolated")

    async def exercise() -> None:
        import httpx

        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                results = await asyncio.gather(
                    *(client.get(PATH, headers=HEADERS) for _ in range(8))
                )
                assert entered.is_set() and all(r.status_code == 503 for r in results)
                overloaded = await client.get(PATH, headers=HEADERS)
                assert overloaded.status_code == 429 and overloaded.headers["Retry-After"] == "1"
        finally:
            done.set()

    asyncio.run(exercise())


def test_public_contract_and_operator_approval(
    prepared: tuple[Path, ZebraAgentSettings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    import zebra_agent_api.host_registry_admin as operator

    path, settings = prepared
    contract_path = (
        Path(__file__).parents[2] / "docs/contracts/host-registry-management-v1.openapi.json"
    )
    contract = json.loads(contract_path.read_text())
    assert set(contract["paths"][PATH]) == {"get", "put"}
    schema = contract["components"]["schemas"]["Apply"]
    assert set(schema["required"]) == {"expectedRevision", "operationId", "active"}
    assert schema["additionalProperties"] is False
    value = json.loads(path.read_text())
    value["trustRevision"] = 2
    write(path, value)
    monkeypatch.setattr(operator, "load_settings", lambda: settings)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "approve",
            "--expected-revision",
            "1",
            "--deployment-namespace",
            value["deploymentNamespace"],
        ],
    )
    assert operator.main() == 0
    assert operator.main() == 1  # CAS does not re-approve the same revision.
    headers = {**HEADERS, "X-Runtime-Trust-Revision": "2"}
    with client_for(path, settings) as client:
        assert client.get(PATH, headers=headers).status_code == 200


def test_slow_request_body_releases_slot(tmp_path: Path) -> None:
    import httpx

    app = FastAPI()
    register_host_registry_management(app, load_settings({}), "isolated")

    async def slow() -> object:
        await asyncio.sleep(0.3)
        yield b"{}"

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.put(
                PATH, headers={**HEADERS, "Content-Type": "application/json"}, content=slow()
            )
            assert response.status_code == 400
            # Following request reaches configuration failure, not leaked-capacity429.
            assert (await client.get(PATH, headers=HEADERS)).status_code == 503

    asyncio.run(exercise())


def test_nested_json_errors_are_sanitized(prepared: tuple[Path, ZebraAgentSettings]) -> None:
    path, settings = prepared
    nested = "[" * 1200 + "null" + "]" * 1200
    with client_for(path, settings) as client:
        bad_body = client.put(
            PATH, headers={**HEADERS, "Content-Type": "application/json"}, content=nested
        )
        assert bad_body.status_code == 400 and bad_body.headers["cache-control"] == "no-store"
        path.write_text(nested)
        bad_config = client.get(PATH, headers=HEADERS)
        assert bad_config.status_code == 503 and bad_config.headers["cache-control"] == "no-store"


def test_uncertain_commit_reconciles_once(
    prepared: tuple[Path, ZebraAgentSettings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager
    from typing import Any

    import psycopg
    from agent_storage.postgres.database import PostgresDatabase

    path, settings = prepared
    original = PostgresDatabase.connect_task_io
    failures = [True]

    @contextmanager
    def committed_then_unknown(self: PostgresDatabase, **kwargs: Any) -> Iterator[Any]:
        with original(self, **kwargs) as connection:
            yield connection
        # Real transaction above has committed. Its acknowledgment is then lost.
        if failures.pop() if failures else False:
            raise psycopg.OperationalError("commit acknowledgment lost")

    monkeypatch.setattr(PostgresDatabase, "connect_task_io", committed_then_unknown)
    body = {"expectedRevision": 0, "operationId": str(uuid4()), "active": True}
    with client_for(path, settings) as client:
        assert client.put(PATH, headers=HEADERS, json=body).status_code == 503
        replay = client.put(PATH, headers=HEADERS, json=body)
        assert replay.status_code == 200 and replay.json()["replayed"] is True
        assert replay.json()["revision"] == 1
    namespace = json.loads(path.read_text())["deploymentNamespace"]
    with psycopg.connect(settings.database_url) as connection:
        for table, extra in [
            ("host_management_receipts", ""),
            ("host_management_audit", " AND action='apply'"),
        ]:
            assert (
                connection.execute(
                    f"SELECT count(*) FROM {table} WHERE deployment_namespace=%s" + extra,
                    (namespace,),
                ).fetchone()[0]
                == 1
            )


def test_full_app_cors_preflight_is_transport_only(tmp_path: Path) -> None:
    app = create_http_app(tmp_path / "cors.sqlite", settings=load_settings({}))
    with TestClient(app) as client:
        response = client.options(
            PATH,
            headers={
                "Origin": "https://ui.example",
                "Access-Control-Request-Method": "PUT",
            },
        )
        assert response.status_code in {200, 400}
        assert "registry" not in response.text and TOKEN not in response.text
        assert client.options(PATH).status_code == 405


def test_composition_uses_authoritative_cloud_database(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import zebra_agent_api.host_registry_management as transport

    captured: list[ZebraAgentSettings] = []
    original_settings = replace(load_settings({}), host_management_config="/private/approved.json")
    monkeypatch.setattr(transport, "register_runtime_management", lambda *args: None)
    monkeypatch.setattr(
        transport,
        "register_host_registry_management",
        lambda app, settings, namespace: captured.append(settings),
    )
    transport.register_management_routes(
        FastAPI(),
        original_settings,
        lambda: "cloud-a",
        SimpleNamespace(dsn="postgres://actual-cloud"),
    )
    assert captured[0].database_url == "postgres://actual-cloud"
    assert original_settings.database_url != captured[0].database_url
