from __future__ import annotations

import hashlib
import http.client
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from agent_core.domain.identifiers import MemoryId
from agent_core.ports.agent_memory_gateway import (
    ConfirmedMemoryPublication,
    MemoryGatewayDeleteRequest,
    MemoryGatewaySearchRequest,
    MemoryGatewayStatus,
)
from agent_integrations.mem0 import Mem0AgentMemoryGateway, Mem0GatewayConfig

ROOT = Path(__file__).resolve().parents[3]
BASE_URL = "http://127.0.0.1:28088"
ADMIN_KEY = "zebra-mem0-spike-admin-key"
COMPOSE_FILES = (
    ROOT / "docker" / "compose.dependencies.yml",
    ROOT / "docker" / "compose.mem0.yml",
    ROOT / "docker" / "compose.mem0.test.yml",
)
SPIKE_ENV = {
    "ZEBRA_POSTGRES_PASSWORD": "zebra-spike-postgres",
    "ZEBRA_MINIO_ROOT_USER": "zebra-spike",
    "ZEBRA_MINIO_ROOT_PASSWORD": "zebra-spike-minio-password",
    "ZEBRA_MEM0_POSTGRES_PASSWORD": "zebra-spike-mem0-postgres",
    "ZEBRA_MEM0_POSTGRES_PORT": "25433",
    "ZEBRA_MEM0_API_PORT": "28088",
    "ZEBRA_MEM0_ADMIN_API_KEY": ADMIN_KEY,
    "ZEBRA_MEM0_JWT_SECRET": "zebra-mem0-spike-jwt-secret-long-enough",
    "ZEBRA_MEM0_OPENAI_API_KEY": "zebra-local-fake-provider",
}

pytestmark = pytest.mark.skipif(
    os.environ.get("ZEBRA_RUN_MEM0_SPIKE") != "1",
    reason="set ZEBRA_RUN_MEM0_SPIKE=1 to run the isolated Docker contract spike",
)


@pytest.fixture(scope="module")
def mem0_stack() -> Iterator[None]:
    _compose("down", "--volumes", "--remove-orphans", check=False)
    _compose("up", "-d", "--wait", "mem0-api")
    try:
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


def test_authenticated_infer_false_memory_lifecycle(mem0_stack: None) -> None:
    unauthorized = _request("GET", "/memories?user_id=anonymous", authenticated=False)
    assert unauthorized.status == 401

    namespace = _encoded_namespace("opaque-tenant/repo/user-scope")
    zebra_memory_id = "018f0000-0000-7000-8000-000000000001"
    publication: dict[str, Any] = {
        "messages": [{"role": "user", "content": "Zebra prefers concise summaries."}],
        "user_id": namespace,
        "metadata": {
            "zebra_memory_id": zebra_memory_id,
            "zebra_idempotency_key": "delivery-001",
            "zebra_schema_version": 1,
        },
        "infer": False,
    }

    first = _request("POST", "/memories", publication)
    assert first.status == 200
    first_id = _single_result(first.body)["id"]

    duplicate = _request("POST", "/memories", publication)
    assert duplicate.status == 200
    duplicate_id = _single_result(duplicate.body)["id"]
    assert duplicate_id != first_id

    search = _request(
        "POST",
        "/search",
        {
            "query": "concise summaries",
            "filters": {"user_id": namespace, "zebra_memory_id": zebra_memory_id},
            "top_k": 10,
            "explain": True,
        },
    )
    assert search.status == 200
    hits = search.body["results"]
    assert {hit["id"] for hit in hits} >= {first_id, duplicate_id}
    assert all(hit["metadata"]["zebra_memory_id"] == zebra_memory_id for hit in hits)

    other_namespace = _request(
        "POST",
        "/search",
        {
            "query": "concise summaries",
            "filters": {"user_id": _encoded_namespace("different-scope")},
        },
    )
    assert other_namespace.status == 200
    assert other_namespace.body["results"] == []

    expired_zebra_id = "018f0000-0000-7000-8000-000000000002"
    expired = _request(
        "POST",
        "/memories",
        {
            **publication,
            "messages": [{"role": "user", "content": "This memory is expired."}],
            "metadata": {
                **publication["metadata"],
                "zebra_memory_id": expired_zebra_id,
                "zebra_idempotency_key": "delivery-002",
            },
            "expiration_date": "2000-01-01",
        },
    )
    assert expired.status == 200
    expired_id = _single_result(expired.body)["id"]
    hidden_expired = _request(
        "POST",
        "/search",
        {
            "query": "expired",
            "filters": {"user_id": namespace, "zebra_memory_id": expired_zebra_id},
        },
    )
    assert hidden_expired.status == 200
    assert hidden_expired.body["results"] == []
    visible_expired = _request(
        "POST",
        "/search",
        {
            "query": "expired",
            "filters": {"user_id": namespace, "zebra_memory_id": expired_zebra_id},
            "show_expired": True,
        },
    )
    assert visible_expired.status == 200
    assert visible_expired.body["results"] == []
    listed_expired = _request(
        "GET",
        f"/memories?user_id={namespace}&show_expired=true",
    )
    assert listed_expired.status == 200
    assert {item["id"] for item in listed_expired.body["results"]} >= {expired_id}

    update = _request(
        "PUT",
        f"/memories/{first_id}",
        {
            "text": "Zebra prefers concise, evidence-backed summaries.",
            "metadata": publication["metadata"],
        },
    )
    assert update.status == 200

    history = _request("GET", f"/memories/{first_id}/history")
    assert history.status == 200
    assert {entry["event"] for entry in history.body} >= {"ADD", "UPDATE"}

    _compose("restart", "mem0-api")
    _wait_until_healthy()
    persisted = _request("GET", f"/memories/{first_id}")
    assert persisted.status == 200
    assert persisted.body["memory"] == "Zebra prefers concise, evidence-backed summaries."

    provider_failure = _request(
        "POST",
        "/search",
        {"query": "zebra-provider-failure", "filters": {"user_id": namespace}},
    )
    assert provider_failure.status == 502
    assert provider_failure.body["code"] == "provider_unavailable"

    dimension_mismatch = _request(
        "POST",
        "/search",
        {"query": "zebra-dimension-mismatch", "filters": {"user_id": namespace}},
    )
    assert dimension_mismatch.status == 502
    assert dimension_mismatch.body["code"] == "unknown"

    provider_timeout = _request(
        "POST",
        "/search",
        {"query": "zebra-provider-timeout", "filters": {"user_id": namespace}},
        timeout=0.1,
    )
    assert provider_timeout.status == 0
    assert provider_timeout.body["connection_error"] == "TimeoutError"

    assert _request("DELETE", f"/memories/{first_id}").status == 200
    assert _request("DELETE", f"/memories/{duplicate_id}").status == 200
    assert _request("DELETE", f"/memories/{expired_id}").status == 200
    after_delete = _request(
        "POST",
        "/search",
        {"query": "concise summaries", "filters": {"user_id": namespace}},
    )
    assert after_delete.status == 200
    assert after_delete.body["results"] == []


def test_zebra_adapter_matches_pinned_mem0_contract(mem0_stack: None) -> None:
    memory_id = MemoryId(uuid4())
    provider_refs = _ProviderRefs()
    gateway = Mem0AgentMemoryGateway(
        Mem0GatewayConfig(
            enabled=True,
            base_url=BASE_URL,
            api_key=ADMIN_KEY,
            allow_insecure_http=True,
        ),
        provider_refs=provider_refs,
    )

    publication = gateway.publish(
        ConfirmedMemoryPublication(
            memory_id=memory_id,
            namespace="opaque-adapter-contract-scope",
            text="Adapter contract memory.",
            idempotency_key="adapter-contract-delivery",
        )
    )
    assert publication.status is MemoryGatewayStatus.SUCCEEDED
    assert publication.provider_ref is not None
    provider_refs.provider_ref = publication.provider_ref

    search = gateway.search(
        MemoryGatewaySearchRequest(
            namespace="opaque-adapter-contract-scope",
            query="Adapter contract memory.",
        )
    )
    assert search.status is MemoryGatewayStatus.SUCCEEDED
    assert any(hit.memory_id == memory_id for hit in search.hits)

    deletion = gateway.delete(
        MemoryGatewayDeleteRequest(
            memory_id=memory_id,
            namespace="opaque-adapter-contract-scope",
            idempotency_key="adapter-contract-delete",
        )
    )
    assert deletion.status is MemoryGatewayStatus.SUCCEEDED


class _ProviderRefs:
    def __init__(self) -> None:
        self.provider_ref: str | None = None

    def resolve(self, *, memory_id: MemoryId, namespace: str) -> str | None:
        return self.provider_ref


class Response:
    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self.body = body


def _request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    authenticated: bool = True,
    timeout: float = 15,
) -> Response:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if authenticated:
        headers["X-API-Key"] = ADMIN_KEY
    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Response(response.status, _decode(response.read()))
    except urllib.error.HTTPError as exc:
        return Response(exc.code, _decode(exc.read()))
    except (OSError, http.client.HTTPException) as exc:
        return Response(0, {"connection_error": type(exc).__name__})


def _decode(payload: bytes) -> Any:
    return json.loads(payload) if payload else None


def _single_result(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload["results"]
    assert len(results) == 1
    result = results[0]
    assert isinstance(result, dict)
    return result


def _encoded_namespace(namespace: str) -> str:
    return "zebra:" + hashlib.sha256(namespace.encode("utf-8")).hexdigest()


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose"]
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


def _wait_until_healthy() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        response = _request("GET", "/auth/setup-status")
        if response.status == 200:
            return
        time.sleep(1)
    raise AssertionError("Mem0 API did not become healthy after restart")
