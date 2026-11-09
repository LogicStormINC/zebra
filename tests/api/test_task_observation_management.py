from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from agent_storage import apply_postgres_migrations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from zebra_agent_api.host_registry_config import load_host_management_config
from zebra_agent_api.task_observation_management import register_task_observation_management
from zebra_agent_config import ZebraAgentSettings, load_settings

TOKEN = "rthm_" + "b" * 43
PATH = "/management/v1/task-observations"
HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "X-Runtime-Deployment": "runtime-a",
    "X-Runtime-Audience": "management-a",
    "X-Runtime-Product": "a",
    "X-Runtime-Environment": "dev",
    "X-Runtime-Trust-Revision": "1",
}
SECRET_TITLE = "机密标题不应出域 secret-title-must-not-leave"


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
        "actions": ["tasks.read"],
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
    }


def write(path: Path, value: dict[str, object]) -> None:
    tmp = path.with_suffix(".new")
    tmp.write_text(json.dumps(value))
    tmp.chmod(0o600)
    tmp.replace(path)


def seed(dsn: str, namespace: str, *, title: str = "Task", status: str = "running") -> str:
    identity = uuid4()
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "INSERT INTO session_projections (deployment_namespace, session_id, title, status, "
            "created_at, updated_at, current_sequence) VALUES (%s, %s, %s, %s, "
            "clock_timestamp(), clock_timestamp(), 7)",
            (namespace, identity, title, status),
        )
        connection.execute(
            "INSERT INTO agent_tasks (deployment_namespace, task_id, root_session_id, "
            "active_segment_id, created_at, updated_at) VALUES (%s, %s, %s, %s, "
            "clock_timestamp(), clock_timestamp())",
            (namespace, identity, identity, identity),
        )
        connection.execute(
            "INSERT INTO execution_segments (deployment_namespace, session_id, task_id, "
            "predecessor_id, segment_index, visibility) VALUES (%s, %s, %s, NULL, 0, 'internal')",
            (namespace, identity, identity),
        )
    return str(identity)


@pytest.fixture(scope="module")
def dsn() -> Iterator[str]:
    container = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "-e",
            "POSTGRES_PASSWORD=isolated-task-observation",
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
        url = f"postgres://postgres:isolated-task-observation@{address}/postgres?sslmode=disable"
        apply_postgres_migrations(url)
        yield url
    finally:
        subprocess.run(["docker", "rm", "-fv", container], check=True, capture_output=True)


@pytest.fixture
def prepared(
    tmp_path: Path, dsn: str
) -> tuple[Path, ZebraAgentSettings, str, list[str], str]:
    from agent_storage.postgres.host_management import HostManagementStore

    ns = "task-observation-" + uuid4().hex
    path = tmp_path / "config.json"
    write(path, config(ns))
    cfg = load_host_management_config(str(path), ns)
    HostManagementStore(dsn, deployment_namespace=ns).approve(cfg.trust, 0)
    mine = [seed(dsn, ns, title=SECRET_TITLE) for _ in range(2)]
    foreign = seed(dsn, "foreign-" + uuid4().hex, title="foreign")
    settings = replace(
        load_settings({}), database_url=dsn, host_management_config=str(path)
    )
    return path, settings, ns, mine, foreign


def client(settings: ZebraAgentSettings, namespace: str) -> TestClient:
    app = FastAPI()
    register_task_observation_management(app, settings, namespace)
    return TestClient(app)


def test_observes_only_own_namespace_without_user_content(
    prepared: tuple[Path, ZebraAgentSettings, str, list[str], str],
) -> None:
    _path, settings, ns, mine, foreign = prepared
    with client(settings, ns) as http:
        response = http.get(PATH, headers=HEADERS)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["contractVersion"] == "task-observation-management/1"
        assert body["namespace"] == ns
        assert {task["taskId"] for task in body["tasks"]} == set(mine)
        assert foreign not in json.dumps(body)
        for task in body["tasks"]:
            assert set(task) == {"taskId", "status", "activeSegmentId", "currentSequence"}
            assert task["status"] == "running"
            assert task["currentSequence"] == 7
        assert SECRET_TITLE not in json.dumps(body)


def test_transport_and_authorization_negatives(
    prepared: tuple[Path, ZebraAgentSettings, str, list[str], str],
) -> None:
    path, settings, ns, _mine, _foreign = prepared
    with client(settings, ns) as http:
        assert (
            http.get(
                PATH, headers={**HEADERS, "Authorization": "Bearer rtmg_" + "a" * 43}
            ).status_code
            == 401
        )
        assert http.get(PATH, headers={**HEADERS, "X-Runtime-Product": "other"}).status_code == 403
        assert http.get(PATH, headers={**HEADERS, "Cookie": "a=b"}).status_code == 400
        assert http.get(PATH + "?limit=5", headers=HEADERS).status_code == 400
        assert http.post(PATH, headers=HEADERS).status_code == 405
        assert (
            http.put(
                PATH,
                headers=HEADERS,
                json={"expectedRevision": 0, "operationId": str(uuid4()), "active": True},
            ).status_code
            == 405
        )
        assert http.get(PATH, headers=HEADERS).status_code == 200
        changed = json.loads(path.read_text())
        changed["actions"] = ["host-registry.read"]
        write(path, changed)
        assert http.get(PATH, headers=HEADERS).status_code == 403
        changed["actions"] = ["tasks.read"]
        write(path, changed)
        assert http.get(PATH, headers=HEADERS).status_code == 200


def test_unavailable_without_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    write(path, config("isolated"))
    settings = replace(
        load_settings({}), database_url="", host_management_config=str(path)
    )
    with client(settings, "isolated") as http:
        assert http.get(PATH, headers=HEADERS).status_code == 503


def test_public_observation_contract() -> None:
    contract = json.loads(
        (
            Path(__file__).parents[2]
            / "docs/contracts/task-observation-management-v1.openapi.json"
        ).read_text()
    )
    assert set(contract["paths"][PATH]) == {"get"}
    schemas = contract["components"]["schemas"]
    assert schemas["Observation"]["properties"]["contractVersion"]["const"] == (
        "task-observation-management/1"
    )
    assert set(schemas["Observation"]["required"]) == {"contractVersion", "namespace", "tasks"}
    assert set(schemas["TaskCoordinates"]["required"]) == {
        "taskId",
        "status",
        "activeSegmentId",
        "currentSequence",
    }
    assert schemas["TaskCoordinates"]["additionalProperties"] is False
    assert "title" not in schemas["TaskCoordinates"]["properties"]
