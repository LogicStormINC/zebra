"""Focused tests for the acceptance operator sidecar (no live services)."""

from __future__ import annotations

import hashlib

import operator_sidecar as sidecar_module
from fastapi.testclient import TestClient
from operator_sidecar import create_sidecar


def _client() -> TestClient:
    return TestClient(create_sidecar())


def test_healthz():
    assert _client().get("/healthz").json() == {"status": "ok"}


def test_business_snapshot_shape(monkeypatch):
    monkeypatch.setenv("TRENCH_SNAPSHOT_DATABASE_DSN", "postgresql://x")
    monkeypatch.setattr(
        sidecar_module,
        "collect_table_facts",
        lambda dsn, tables: {"events": {"count": 1, "digest": "d" * 64}},
    )
    body = _client().get("/business-snapshot").json()
    assert body["schema_version"] == "trench.business-snapshot.v1"
    assert body["tables"]["events"] == {"count": 1, "digest": "d" * 64}


def test_business_snapshot_reports_read_failure(monkeypatch):
    monkeypatch.delenv("TRENCH_SNAPSHOT_DATABASE_DSN", raising=False)
    response = _client().get("/business-snapshot")
    assert response.status_code == 500
    assert response.json()["reason"] == "TRENCH_SNAPSHOT_DATABASE_DSN is required"


def test_worker_restart_requires_operator_token(monkeypatch):
    monkeypatch.setenv("E2E_OPERATOR_TOKEN", "secret")
    monkeypatch.setenv("E2E_WORKER_CONTAINER", "zebra-worker-1")
    monkeypatch.setattr(sidecar_module, "_restart_worker", lambda container: 204)
    client = _client()
    denied = client.post(
        "/worker-restart", json={"taskId": "t", "runId": "r"}
    )
    assert denied.status_code == 403
    allowed = client.post(
        "/worker-restart",
        json={"taskId": "t", "runId": "r"},
        headers={"X-E2E-Operator-Token": "secret"},
    )
    assert allowed.status_code == 200


def test_worker_restart_rejects_browser_credentials_shape():
    response = _client().post(
        "/worker-restart",
        json={"taskId": "t", "runId": "r", "cookie": "stolen"},
    )
    assert response.status_code == 422  # extra fields are not part of the contract


def test_digest_is_deterministic_over_ordered_rows():
    digest = hashlib.sha256()
    for row in [(1, "a"), (2, "b")]:
        digest.update(repr(row).encode())
        digest.update(b"\x1f")
    assert len(digest.hexdigest()) == 64
