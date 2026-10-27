from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from agent_storage import apply_postgres_migrations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from zebra_agent_api.host_connector_management import register_host_connector_management
from zebra_agent_api.host_registry_config import load_host_management_config
from zebra_agent_api.host_registry_management import register_host_registry_management
from zebra_agent_config import ZebraAgentSettings, load_settings

TOKEN = "rthm_" + "a" * 43
PATH = "/management/v1/host-connector"
HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "X-Runtime-Deployment": "runtime-a",
    "X-Runtime-Audience": "management-a",
    "X-Runtime-Product": "a",
    "X-Runtime-Environment": "dev",
    "X-Runtime-Trust-Revision": "1",
}


def profile(revision: int = 1) -> dict[str, object]:
    return {
        "hostAppId": "host-a",
        "connectorId": "connector-a",
        "profileRevision": revision,
        "baseUri": "https://host.example",
        "manifestPath": "/tools/manifest",
        "invokePathTemplate": "/tools/invoke",
        "reconcilePathTemplate": "/tools/reconcile",
        "supportedProtocolVersions": ["host-tools/v1"],
        "workloadIdentityRef": "workload-a",
        "credentialRef": "credential-a",
        "networkPolicyRef": "network-a",
        "manifestBindingPolicy": "declared",
        "status": "published",
    }


def config(namespace: str) -> dict[str, object]:
    return {
        "deploymentId": "runtime-a",
        "deploymentNamespace": namespace,
        "audience": "management-a",
        "productId": "a",
        "environment": "dev",
        "trustRevision": 1,
        "credentialSha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
        "expiresAt": "2099-01-01T00:00:00Z",
        "actions": ["connector.read", "connector.write"],
        "registry": {
            "hostAppId": "host-a",
            "namespaceId": "tenant-a",
            "issuer": "https://broker.example",
            "audience": "runtime-a",
            "jwksUri": "https://broker.example/jwks",
            "allowedOrigins": ["https://ui.example"],
            "algorithms": ["RS256"],
            "policyVersion": "v1",
            "active": True,
        },
        "connectorProfile": profile(),
    }


def write(path: Path, value: dict[str, object]) -> None:
    tmp = path.with_suffix(".new")
    tmp.write_text(json.dumps(value))
    tmp.chmod(0o600)
    tmp.replace(path)


@pytest.fixture(scope="module")
def dsn() -> Iterator[str]:
    container = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "-e",
            "POSTGRES_PASSWORD=isolated-connector-api",
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
            if (
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        container,
                        "pg_isready",
                        "-h",
                        "127.0.0.1",
                        "-U",
                        "postgres",
                    ],
                    capture_output=True,
                ).returncode
                == 0
            ):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("owned PostgreSQL unavailable")
        url = f"postgres://postgres:isolated-connector-api@{address}/postgres?sslmode=disable"
        apply_postgres_migrations(url)
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", container], check=True, capture_output=True)


@pytest.fixture
def prepared(tmp_path: Path, dsn: str) -> tuple[Path, ZebraAgentSettings, str]:
    from agent_storage.postgres.host_management import HostManagementStore

    ns = "connector-" + uuid4().hex
    path = tmp_path / "config.json"
    write(path, config(ns))
    cfg = load_host_management_config(str(path), ns)
    HostManagementStore(dsn, deployment_namespace=ns).approve(cfg.trust, 0)
    return path, replace(load_settings({}), database_url=dsn, host_management_config=str(path)), ns


def client(settings: ZebraAgentSettings, namespace: str) -> TestClient:
    app = FastAPI()
    register_host_connector_management(app, settings, namespace)
    register_host_registry_management(app, settings, namespace)
    return TestClient(app)


def test_fixed_template_cas_and_current_vs_approved(
    prepared: tuple[Path, ZebraAgentSettings, str],
) -> None:
    from agent_storage.postgres.host_management import HostManagementStore

    path, settings, ns = prepared
    body = {"expectedRevision": 0, "operationId": str(uuid4()), "active": True}
    with client(settings, ns) as one, client(settings, ns) as two:
        before = one.get(PATH, headers=HEADERS)
        assert before.status_code == 200
        assert (
            before.json()["profile"] is None
            and before.json()["approvedProfile"]["profileRevision"] == 1
        )
        assert one.get("/management/v1/host-registry", headers=HEADERS).status_code == 403
        created = one.put(PATH, headers=HEADERS, json=body)
        assert created.status_code == 200
        assert created.json()["revision"] == 1 and created.json()["profile"]["profileRevision"] == 1
        assert two.put(PATH, headers=HEADERS, json=body).json()["replayed"]
        assert (
            one.put(PATH, headers=HEADERS, json={**body, "operationId": str(uuid4())}).status_code
            == 409
        )
        value = json.loads(path.read_text())
        value["trustRevision"] = 2
        value["connectorProfile"] = profile(2)
        write(path, value)
        cfg = load_host_management_config(str(path), ns)
        HostManagementStore(settings.database_url, deployment_namespace=ns).approve(cfg.trust, 1)
        newheaders = {**HEADERS, "X-Runtime-Trust-Revision": "2"}
        current = one.get(PATH, headers=newheaders).json()
        assert (
            current["profile"]["profileRevision"] == 1
            and current["approvedProfile"]["profileRevision"] == 2
        )
        disabled = one.put(
            PATH,
            headers=newheaders,
            json={"expectedRevision": 1, "operationId": str(uuid4()), "active": False},
        )
        assert disabled.status_code == 200 and disabled.json()["revision"] == 2
        assert (
            disabled.json()["profile"]["profileRevision"] == 1
            and not disabled.json()["binding"]["active"]
        )
        enabled = two.put(
            PATH,
            headers=newheaders,
            json={"expectedRevision": 2, "operationId": str(uuid4()), "active": True},
        )
        assert enabled.status_code == 200 and enabled.json()["profile"]["profileRevision"] == 2
        assert enabled.json()["binding"]["active"] and enabled.json()["revision"] == 3
        assert one.get(PATH, headers=HEADERS).status_code == 403


@pytest.mark.parametrize(
    "change",
    [
        {"hostAppId": "other"},
        {"profileRevision": True},
        {"profileRevision": "1"},
        {"baseUri": "https://user:pass@host.example"},
        {"baseUri": "https://host.example/prefix"},
        {"status": "revoked"},
        {"manifestBindingPolicy": None},
        {"unknown": True},
        {"supportedProtocolVersions": ["ok", "ok"]},
        {"credentialRef": "literal-secret"},
    ],
)
def test_template_strictness(tmp_path: Path, change: dict[str, object]) -> None:
    path = tmp_path / "config.json"
    value = config("isolated")
    value["connectorProfile"] = {**profile(), **change}
    write(path, value)
    with pytest.raises((ValueError, TypeError)):
        load_host_management_config(str(path), "isolated")


def test_missing_template_cannot_gain_connector_actions(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    value = config("isolated")
    value.pop("connectorProfile")
    write(path, value)
    with pytest.raises(ValueError):
        load_host_management_config(str(path), "isolated")
    value["actions"] = ["host-registry.read"]
    write(path, value)
    old = load_host_management_config(str(path), "isolated")
    assert old.connector_profile is None
    original_fingerprint = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert old.trust.fingerprint == original_fingerprint


def test_connector_transport_and_explicit_actions(
    prepared: tuple[Path, ZebraAgentSettings, str],
) -> None:
    path, settings, ns = prepared
    body = {"expectedRevision": 0, "operationId": str(uuid4()), "active": True}
    with client(settings, ns) as http:
        assert http.put(PATH, headers=HEADERS, json={**body, "active": False}).status_code == 409
        assert (
            http.get(
                PATH, headers={**HEADERS, "Authorization": "Bearer rtmg_" + "a" * 43}
            ).status_code
            == 401
        )
        assert (
            http.get(PATH, headers=[*HEADERS.items(), ("X-Runtime-Product", "a")]).status_code
            == 403
        )
        assert http.get(PATH, headers={**HEADERS, "Cookie": "a=b"}).status_code == 400
        assert http.get(PATH + "?profile=other", headers=HEADERS).status_code == 400
        assert (
            http.put(PATH, headers=HEADERS, json={**body, "profile": profile()}).status_code == 400
        )
        deep = "[" * 1200 + "null" + "]" * 1200
        response = http.put(
            PATH, headers={**HEADERS, "Content-Type": "application/json"}, content=deep
        )
        assert response.status_code == 400 and response.headers["cache-control"] == "no-store"
        assert http.post(PATH, headers=HEADERS).status_code == 405
        changed = json.loads(path.read_text())
        changed["actions"] = ["host-registry.read"]
        write(path, changed)
        assert http.get(PATH, headers=HEADERS).status_code == 403
        changed["actions"] = ["connector.read"]
        write(path, changed)
        assert http.put(PATH, headers=HEADERS, json=body).status_code == 403
        path.write_text(deep)
        assert http.get(PATH, headers=HEADERS).status_code == 503


def test_unknown_real_commit_and_stale_replica(
    prepared: tuple[Path, ZebraAgentSettings, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager
    from typing import Any

    import psycopg
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.host_management import HostManagementStore

    path, settings, ns = prepared
    original = PostgresDatabase.connect_task_io
    once = [True]

    @contextmanager
    def unknown(self: PostgresDatabase, **kwargs: Any) -> Iterator[Any]:
        with original(self, **kwargs) as connection:
            yield connection
        if once.pop() if once else False:
            raise psycopg.OperationalError("COMMIT acknowledgment lost")

    monkeypatch.setattr(PostgresDatabase, "connect_task_io", unknown)
    body = {"expectedRevision": 0, "operationId": str(uuid4()), "active": True}
    old = path.with_name("old-config.json")
    write(old, json.loads(path.read_text()))
    oldsettings = replace(settings, host_management_config=str(old))
    with client(settings, ns) as one, client(oldsettings, ns) as stale:
        response = one.put(PATH, headers=HEADERS, json=body)
        assert response.status_code == 503
        replay = stale.put(PATH, headers=HEADERS, json=body)
        assert replay.status_code == 200 and replay.json()["replayed"]
        value = json.loads(path.read_text())
        value["trustRevision"] = 2
        value["connectorProfile"] = profile(2)
        write(path, value)
        cfg = load_host_management_config(str(path), ns)
        HostManagementStore(settings.database_url, deployment_namespace=ns).approve(cfg.trust, 1)
        assert stale.get(PATH, headers=HEADERS).status_code == 503
        assert stale.put(PATH, headers=HEADERS, json=body).status_code == 503
    with psycopg.connect(settings.database_url) as connection:
        for table in (
            "host_connector_profiles",
            "host_connector_management_receipts",
            "host_connector_management_audit",
        ):
            assert (
                connection.execute(
                    f"SELECT count(*) FROM {table} WHERE deployment_namespace=%s", (ns,)
                ).fetchone()[0]
                == 1
            )


def test_late_connector_config_read_keeps_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import threading

    import httpx
    import zebra_agent_api.host_connector_management as transport

    release = threading.Event()

    def slow(*args: object) -> object:
        release.wait(2)
        raise ValueError("private configuration")

    monkeypatch.setattr(transport, "load_host_management_config", slow)
    monkeypatch.setattr(transport, "REQUEST_TIMEOUT", 0.03)
    app = FastAPI()
    register_host_connector_management(app, load_settings({}), "isolated")

    async def exercise() -> None:
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as http:
                replies = await asyncio.gather(*(http.get(PATH, headers=HEADERS) for _ in range(8)))
                assert all(r.status_code == 503 for r in replies)
                overloaded = await http.get(PATH, headers=HEADERS)
                assert overloaded.status_code == 429 and overloaded.headers["retry-after"] == "1"
        finally:
            release.set()

    asyncio.run(exercise())


def test_public_connector_contract() -> None:
    contract = json.loads(
        (
            Path(__file__).parents[2] / "docs/contracts/host-connector-management-v1.openapi.json"
        ).read_text()
    )
    assert set(contract["paths"][PATH]) == {"get", "put"}
    schemas = contract["components"]["schemas"]
    assert (
        schemas["Snapshot"]["properties"]["contractVersion"]["const"]
        == "host-connector-management/1"
    )
    assert set(schemas["Snapshot"]["required"]) == {
        "contractVersion",
        "binding",
        "profile",
        "approvedProfile",
        "revision",
        "replayed",
    }
    assert set(schemas["Profile"]["required"]) == set(profile()) | {"profileDigest"}
    assert schemas["Apply"]["additionalProperties"] is False
    assert set(schemas["Apply"]["required"]) == {"expectedRevision", "operationId", "active"}
