"""Management-only Mem0 namespace reset/rebuild probe.

This test deliberately fails closed when the pinned REST server does not expose
bounded pagination.  A list endpoint that silently truncates results cannot be
used to implement a safe scoped reset.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
PROJECT = "zebra-mem0-reset-spike"
BASE_URL = "http://127.0.0.1:28098"
PROXY_URL = "http://127.0.0.1:28099"
ADMIN_KEY = "zebra-mem0-reset-spike-admin-key"
PAGE_SIZE = 3
COMPOSE_FILES = (
    ROOT / "docker" / "compose.dependencies.yml",
    ROOT / "docker" / "compose.mem0.yml",
    ROOT / "docker" / "compose.mem0.test.yml",
)
SPIKE_ENV = {
    "ZEBRA_POSTGRES_PASSWORD": "zebra-reset-spike-postgres",
    "ZEBRA_MINIO_ROOT_USER": "zebra-reset-spike",
    "ZEBRA_MINIO_ROOT_PASSWORD": "zebra-reset-spike-minio-password",
    "ZEBRA_MEM0_POSTGRES_PASSWORD": "zebra-reset-spike-mem0-postgres",
    "ZEBRA_MEM0_POSTGRES_PORT": "25443",
    "ZEBRA_MEM0_API_PORT": "28098",
    "ZEBRA_MEM0_PROXY_PORT": "28099",
    "ZEBRA_MEM0_ADMIN_API_KEY": ADMIN_KEY,
    "ZEBRA_MEM0_JWT_SECRET": "zebra-reset-spike-jwt-secret-long-enough",
    "ZEBRA_MEM0_OPENAI_API_KEY": "zebra-reset-spike-fake-provider",
}

pytestmark = pytest.mark.skipif(
    os.environ.get("ZEBRA_RUN_MEM0_RESET_SPIKE") != "1",
    reason="set ZEBRA_RUN_MEM0_RESET_SPIKE=1 to run the isolated Docker reset spike",
)


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    body: Any


@pytest.fixture(scope="module")
def mem0_stack() -> Iterator[None]:
    _compose("down", "--volumes", "--remove-orphans", check=False)
    _compose("up", "-d", "--wait", "mem0-response-loss")
    try:
        _wait_until_ready()
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


def test_scoped_reset_rebuild_and_unknown_publish(mem0_stack: None) -> None:
    unauthorized = _request("GET", "/memories?user_id=anonymous", authenticated=False)
    assert unauthorized.status == 401

    pagination = _pagination_contract()
    a_g1 = _scope("tenant-a", 1)
    a_g2 = _scope("tenant-a", 2)
    a_g3 = _scope("tenant-a", 3)
    b_g1 = _scope("tenant-b", 1)

    a_g1_memory_ids: list[str] = []
    for index in range(6):
        a_g1_memory_ids.append(
            _publish(
                a_g1,
                f"tenant-a generation one memory {index}",
                generation=1,
            )
        )

    duplicate_payload = "tenant-a generation one duplicate"
    duplicate_first = _publish(a_g1, duplicate_payload, generation=1)
    duplicate_second = _publish(a_g1, duplicate_payload, generation=1)
    assert duplicate_first != duplicate_second
    a_g1_memory_ids.extend((duplicate_first, duplicate_second))

    expired_id = _publish(
        a_g1,
        "tenant-a generation one expired memory",
        generation=1,
        expiration_date="2000-01-01",
    )
    a_g1_memory_ids.append(expired_id)

    b_g1_memory_ids = [
        _publish(b_g1, f"tenant-b generation one memory {index}", generation=1)
        for index in range(2)
    ]

    unknown_memory_id = str(uuid4())
    unknown = _request(
        "POST",
        "/memories",
        _publication(
            a_g1,
            "tenant-a generation one response-loss memory",
            unknown_memory_id,
            generation=1,
        ),
        base_url=PROXY_URL,
    )
    assert unknown.status == 0, "response-loss proxy must produce an unknown outcome"
    # No retry is made.  Discovery below is the only allowed reconciliation path.

    a_g1_rows = _list_scope(a_g1, pagination)
    b_g1_rows = _list_scope(b_g1, pagination)
    assert len(a_g1_rows) >= len(a_g1_memory_ids) + 1
    assert {row["metadata"]["zebra_memory_id"] for row in a_g1_rows} >= {
        *a_g1_memory_ids,
        unknown_memory_id,
    }
    assert {row["metadata"]["zebra_memory_id"] for row in b_g1_rows} >= set(b_g1_memory_ids)
    assert all(row["metadata"]["zebra_generation"] == 1 for row in a_g1_rows)
    assert all(row["metadata"]["zebra_generation"] == 1 for row in b_g1_rows)

    expired_search = _search(a_g1, expired_id, "expired")
    assert expired_search.status == 200
    assert expired_search.body["results"] == []
    assert _search(a_g1, a_g1_memory_ids[0], "generation one").body["results"]
    assert _search(b_g1, b_g1_memory_ids[0], "generation one").body["results"]
    assert _db_memory_count(a_g1) >= len(a_g1_memory_ids) + 1
    assert _db_memory_count(b_g1) >= len(b_g1_memory_ids)

    _compose("restart", "mem0-api")
    _wait_until_ready()
    assert len(_list_scope(a_g1, pagination)) >= len(a_g1_memory_ids) + 1

    # Scoped purge enumerates the exact generation and converges on 200/404.
    for row in a_g1_rows:
        first_delete = _request("DELETE", f"/memories/{row['id']}")
        assert first_delete.status in {200, 404}
        second_delete = _request("DELETE", f"/memories/{row['id']}")
        assert second_delete.status in {200, 404}

    assert _list_scope(a_g1, pagination) == []
    assert _search(a_g1, a_g1_memory_ids[0], "generation one").body["results"] == []
    assert len(_list_scope(b_g1, pagination)) >= len(b_g1_memory_ids)
    assert _db_memory_count(a_g1) == 0
    assert _db_memory_count(b_g1) >= len(b_g1_memory_ids)

    # A rebuild gets a fresh generation; the old generation remains empty.
    a_g2_memory_ids = [
        _publish(a_g2, f"tenant-a generation two rebuilt memory {index}", generation=2)
        for index in range(2)
    ]
    assert {row["metadata"]["zebra_memory_id"] for row in _list_scope(a_g2, pagination)} >= set(
        a_g2_memory_ids
    )
    assert _list_scope(a_g1, pagination) == []

    reset_fault = _request("POST", "/__test__/reset-fault", base_url=PROXY_URL, authenticated=False)
    assert reset_fault.status == 204
    unknown_g2_id = str(uuid4())
    unknown_g2 = _request(
        "POST",
        "/memories",
        _publication(
            a_g2,
            "tenant-a generation two response-loss memory",
            unknown_g2_id,
            generation=2,
        ),
        base_url=PROXY_URL,
    )
    assert unknown_g2.status == 0
    assert unknown_g2_id in {
        row["metadata"]["zebra_memory_id"] for row in _list_scope(a_g2, pagination)
    }

    # Unknown g2 is quarantined; rebuilding proceeds only in g3.
    a_g3_memory_ids = [
        _publish(a_g3, f"tenant-a generation three rebuilt memory {index}", generation=3)
        for index in range(2)
    ]
    assert {row["metadata"]["zebra_memory_id"] for row in _list_scope(a_g3, pagination)} >= set(
        a_g3_memory_ids
    )
    assert _list_scope(a_g1, pagination) == []
    assert len(_list_scope(a_g2, pagination)) >= len(a_g2_memory_ids) + 1
    assert len(_list_scope(b_g1, pagination)) >= len(b_g1_memory_ids)
    assert _search(a_g3, a_g3_memory_ids[0], "generation three").body["results"]
    assert _db_memory_count(a_g2) >= len(a_g2_memory_ids) + 1
    assert _db_memory_count(a_g3) >= len(a_g3_memory_ids)


def _publication(
    scope: str,
    text: str,
    memory_id: str,
    *,
    generation: int,
    expiration_date: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": text}],
        "user_id": scope,
        "metadata": {
            "zebra_memory_id": memory_id,
            "zebra_idempotency_key": f"reset-spike-{memory_id}",
            "zebra_generation": generation,
            "zebra_schema_version": 1,
        },
        "infer": False,
    }
    if expiration_date is not None:
        payload["expiration_date"] = expiration_date
    return payload


def _publish(scope: str, text: str, *, generation: int, expiration_date: str | None = None) -> str:
    memory_id = str(uuid4())
    response = _request(
        "POST",
        "/memories",
        _publication(
            scope,
            text,
            memory_id,
            generation=generation,
            expiration_date=expiration_date,
        ),
    )
    assert response.status == 200, response.body
    results = _results(response.body)
    assert len(results) == 1
    return str(results[0]["id"])


def _search(scope: str, memory_id: str, query: str) -> Response:
    return _request(
        "POST",
        "/search",
        {
            "query": query,
            "filters": {"user_id": scope, "zebra_memory_id": memory_id},
            "top_k": 10,
        },
    )


def _pagination_contract() -> tuple[str, str, str]:
    response = _request("GET", "/openapi.json")
    assert response.status == 200, response.body
    operation = response.body.get("paths", {}).get("/memories", {}).get("get", {})
    names = {parameter.get("name") for parameter in operation.get("parameters", [])}
    for mode, first, second in (("page", "page", "page_size"), ("offset", "offset", "limit")):
        if {first, second} <= names:
            return mode, first, second
    pytest.fail(
        "Blocked: pinned Mem0 GET /memories exposes no documented bounded pagination "
        f"(parameters={sorted(name for name in names if name)})"
    )


def _list_scope(scope: str, pagination: tuple[str, str, str]) -> list[dict[str, Any]]:
    mode, first, second = pagination
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, 101):
        values = {"user_id": scope, "show_expired": "true"}
        if mode == "page":
            values[first] = str(page)
        else:
            values[first] = str((page - 1) * PAGE_SIZE)
        values[second] = str(PAGE_SIZE)
        response = _request("GET", f"/memories?{urlencode(values)}")
        assert response.status == 200, response.body
        page_rows = _results(response.body)
        if len(page_rows) > PAGE_SIZE:
            pytest.fail("Blocked: Mem0 ignored the documented page-size bound")
        for row in page_rows:
            row_id = str(row["id"])
            assert row_id not in seen, "pagination repeated an object; reset cannot be exact"
            assert isinstance(row.get("metadata"), dict), f"Mem0 row has no metadata: {row}"
            seen.add(row_id)
            rows.append(row)
        if not page_rows or len(page_rows) < PAGE_SIZE:
            return rows
    pytest.fail("Blocked: bounded Mem0 enumeration exceeded 100 pages")


def _results(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        result = payload
    elif isinstance(payload, dict):
        result = payload.get("results", [])
    else:
        result = []
    assert isinstance(result, list)
    normalized: list[dict[str, Any]] = []
    for item in result:
        assert isinstance(item, dict)
        normalized.append(item)
    return normalized


def _db_memory_count(scope: str) -> int:
    """Read the pinned PGVector payload table; never mutate provider state here."""
    import psycopg
    from psycopg import sql

    with psycopg.connect(
        host="127.0.0.1",
        port=int(SPIKE_ENV["ZEBRA_MEM0_POSTGRES_PORT"]),
        dbname="mem0",
        user="mem0",
        password=SPIKE_ENV["ZEBRA_MEM0_POSTGRES_PASSWORD"],
        connect_timeout=5,
    ) as connection:
        table = "zebra_memories"
        exists = connection.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table,),
        ).fetchone()
        assert exists, f"Blocked: Mem0 collection table {table!r} is absent"
        row = connection.execute(
            sql.SQL("SELECT count(*) FROM {} WHERE payload->>'user_id' = %s").format(
                sql.Identifier(table)
            ),
            (scope,),
        ).fetchone()
        assert row is not None
        return int(row[0])


def _scope(namespace: str, generation: int) -> str:
    return "zebra:" + hashlib.sha256(f"{namespace}/g{generation}".encode()).hexdigest()


def _request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    base_url: str = BASE_URL,
    authenticated: bool = True,
    timeout: float = 15,
) -> Response:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if authenticated:
        headers["X-API-Key"] = ADMIN_KEY
    request = Request(base_url + path, data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return Response(response.status, _decode(response.read()))
    except Exception as exc:  # noqa: BLE001 - the probe records unknown transport outcomes
        if isinstance(exc, HTTPError):
            return Response(exc.code, _decode(exc.read()))
        if isinstance(exc, OSError | http.client.HTTPException):
            return Response(0, {"connection_error": type(exc).__name__})
        raise


def _decode(payload: bytes) -> Any:
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload.decode("utf-8")


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose", "--project-name", PROJECT]
    for path in COMPOSE_FILES:
        command.extend(("-f", str(path)))
    command.extend(("--profile", "mem0", *args))
    return subprocess.run(
        command,
        cwd=ROOT,
        env={**os.environ, **SPIKE_ENV},
        check=check,
        capture_output=True,
        text=True,
    )


def _wait_until_ready() -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        response = _request("GET", "/auth/setup-status")
        proxy = _request("GET", "/health", base_url=PROXY_URL, authenticated=False)
        if response.status == 200 and proxy.status == 200:
            return
        time.sleep(1)
    raise AssertionError("Mem0 reset stack did not become healthy")
