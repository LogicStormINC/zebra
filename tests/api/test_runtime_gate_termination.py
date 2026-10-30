"""Real disposable PG/HTTP and late old-snapshot exclusion, no process-stop claim."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.runtime_gate_termination import (
    CONTRACT_DIGEST,
    GateTerminationCommand,
)
from agent_core.domain.runtime_gates import GateCommand
from agent_storage.postgres.host_management import HostManagementStore
from agent_storage.postgres.runtime_gate_termination import RuntimeGateTerminationStore
from agent_storage.postgres.runtime_gates import RuntimeGateStore
from zebra_agent_api.runtime_gate_termination import PATH, register_runtime_gate_termination
from zebra_agent_api.runtime_gate_termination_config import load_runtime_gate_termination_approval

from tests.agent_storage.test_host_management import host_management_dsn  # noqa:F401
from tests.api.test_runtime_gate_management import command, gate  # noqa:F401

TOKEN = "rtgstop_" + "s" * 43


@pytest.fixture
def subject(gate, tmp_path):  # noqa:F811
    value = {
        **gate.value,
        "schema_version": "cloud-agent.runtime-gate-termination-approval/1",
        "contract_digest": CONTRACT_DIGEST,
        "credential_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
        "actions": ["read", "terminate"],
    }
    path = tmp_path / "termination.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    approval = load_runtime_gate_termination_approval(str(path), gate.approval.scope.namespace_id)
    approvals = HostManagementStore(gate.dsn, deployment_namespace=approval.scope.namespace_id)
    approvals.approve(approval.trust, 0)
    cfg = replace(gate.cfg, runtime_gate_termination_config=str(path))
    register_runtime_gate_termination(gate.client.app, cfg, approval.scope.namespace_id)
    headers = {**gate.headers, "Authorization": "Bearer " + TOKEN}
    headers.pop("X-Runtime-Gate-Contract")
    headers["X-Runtime-Gate-Termination-Contract"] = CONTRACT_DIGEST
    return gate, approval, approvals, headers, path, value


def termination(raw, revision=0):
    return {
        "termination_id": str(uuid4()),
        "original_request": raw,
        "expected_gate_revision": revision,
    }


def record(response):
    path = os.environ.get("CA_GATE_TERMINATION_EVIDENCE")
    if path:
        from pathlib import Path

        p = Path(path)
        assert p.is_absolute()
        values = json.loads(p.read_text()) if p.exists() else []
        values.append(
            {
                "method": response.request.method,
                "requestBody": response.request.content.decode(),
                "operationId": response.request.headers.get("X-Runtime-Operation"),
                "body": response.json(),
            }
        )
        p.write_text(json.dumps(values, indent=2) + "\n")


def test_termination_fences_late_original_and_get_recovers_exact_proof(subject):
    g, _, _, headers, _, _ = subject
    raw = json.dumps(command("drain"), separators=(",", ":"))
    request = termination(raw)
    response = g.client.post(PATH, headers=headers, json=request)
    assert response.status_code == 200, response.text
    proof = response.json()["original"]
    assert proof["outcome"] == "no_gate_commit" and proof["original"] is None
    assert proof["originalInputDigest"] == "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
    assert proof["proofScope"] == "original_gate_command_only"
    assert proof["gateRevision"] == 0 and proof["lateSubmissionFenced"] is True
    record(response)
    assert g.client.post(PATH, headers=headers, json=request).status_code == 409
    repeated_source = {**request, "termination_id": str(uuid4())}
    assert g.client.post(PATH, headers=headers, json=repeated_source).status_code == 409
    # Even a delayed request with a different body under the same UUID is rejected.
    for late in (raw, json.dumps({**json.loads(raw), "action": "open"})):
        assert (
            g.client.post(
                "/management/v1/runtime-gates",
                headers={**g.headers, "Content-Type": "application/json"},
                content=late,
            ).status_code
            == 409
        )
    get_headers = {**headers, "X-Runtime-Operation": request["termination_id"]}
    recovered = g.client.get(PATH, headers=get_headers)
    assert recovered.status_code == 200 and recovered.json()["original"] == proof
    record(recovered)
    assert (
        g.client.get(PATH, headers={**get_headers, "X-Runtime-Operation": str(uuid4())}).status_code
        == 404
    )
    assert g.client.get(PATH, headers=g.headers).status_code == 401
    assert g.client.get(PATH, headers=headers).status_code == 400
    assert (
        g.client.post(
            PATH, headers=headers, json={**termination(raw), "safeToStop": True}
        ).status_code
        == 400
    )
    with psycopg.connect(g.dsn) as c:
        with pytest.raises(psycopg.Error), c.transaction():
            c.execute("DELETE FROM runtime_gate_terminations")
    assert g.client.get(PATH, headers=get_headers).json()["original"] == proof


def test_committed_original_is_preserved_never_reversed(subject):
    g, _, _, headers, _, _ = subject
    raw = json.dumps(command("drain"))
    original = g.client.post(
        "/management/v1/runtime-gates",
        headers={**g.headers, "Content-Type": "application/json"},
        content=raw,
    )
    assert original.status_code == 200, original.text
    stale = g.client.post(PATH, headers=headers, json=termination(raw, 0))
    assert stale.status_code == 409
    response = g.client.post(PATH, headers=headers, json=termination(raw, 1))
    assert response.status_code == 200, response.text
    assert response.json()["original"]["outcome"] == "already_committed"
    assert response.json()["original"]["original"] == original.json()["original"]
    record(response)
    assert (
        g.client.get("/management/v1/runtime-gates", headers=g.headers).json()["admission"]
        == "draining"
    )
    changed = json.dumps({**json.loads(raw), "expected_revision": 1})
    assert g.client.post(PATH, headers=headers, json=termination(changed, 1)).status_code == 409


def test_current_termination_revoke_blocks_get_and_post(subject):
    g, approval, approvals, headers, _, _ = subject
    response = g.client.post(PATH, headers=headers, json=termination(json.dumps(command("open"))))
    assert response.status_code == 200
    proof = response.json()["original"]
    revoked = replace(approval.trust, revision=2)
    approvals.approve(revoked, 1)
    assert (
        g.client.get(
            PATH, headers={**headers, "X-Runtime-Operation": proof["terminationId"]}
        ).status_code
        == 403
    )
    assert (
        g.client.post(
            PATH, headers=headers, json=termination(json.dumps(command("open")))
        ).status_code
        == 403
    )


def test_old_repeatable_read_snapshot_cannot_miss_termination(subject, monkeypatch):
    g, approval, _, _, _, _ = subject
    raw = json.dumps(command("drain"))
    source = GateCommand.model_validate_json(raw)
    pending = RuntimeGateStore(g.dsn, g.approval.scope, g.approval.trust)
    started, proceed = Event(), Event()
    original_gate = pending._gate

    def paused(c, *, update=False):
        # _transaction already authorized and established the repeatable-read snapshot.
        started.set()
        assert proceed.wait(5)
        return original_gate(c, update=update)

    monkeypatch.setattr(pending, "_gate", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            pending.change, source, hashlib.sha256(raw.encode()).hexdigest(), lambda: None
        )
        try:
            assert started.wait(5)
            store = RuntimeGateTerminationStore(g.dsn, approval.scope, approval.trust)
            request = GateTerminationCommand.model_validate(termination(raw))
            proof = store.terminate(request, "a" * 64, lambda: None)["original"]
            assert proof["outcome"] == "no_gate_commit"
        finally:
            proceed.set()
        with pytest.raises(psycopg.errors.SerializationFailure):
            future.result(timeout=5)
    with pytest.raises(LookupError):
        g.store.read(str(source.operation_id))


def test_envelope_budget_preserves_maximum_original_and_read_only_authority(subject):
    g, approval, approvals, headers, path, value = subject
    raw = json.dumps(command("open"))
    raw += "\n" * (16384 - len(raw.encode()))
    request = termination(raw)
    response = g.client.post(PATH, headers=headers, json=request)
    assert response.status_code == 200, response.text
    assert response.json()["original"]["originalInputDigest"] == (
        "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
    )
    readonly = {**value, "actions": ["read"], "trust_revision": 2}
    path.write_text(json.dumps(readonly))
    current = load_runtime_gate_termination_approval(str(path), approval.scope.namespace_id)
    approvals.approve(current.trust, 1)
    headers = {**headers, "X-Runtime-Trust-Revision": "2"}
    assert (
        g.client.get(
            PATH, headers={**headers, "X-Runtime-Operation": request["termination_id"]}
        ).status_code
        == 200
    )
    assert (
        g.client.post(
            PATH, headers=headers, json=termination(json.dumps(command("open")))
        ).status_code
        == 403
    )


def test_termination_recheck_rolls_back_fence_and_capacity_preserves_original(subject):
    g, approval, _, headers, _, _ = subject
    store = RuntimeGateTerminationStore(g.dsn, approval.scope, approval.trust)
    raw = json.dumps(command("open"))
    req = GateTerminationCommand.model_validate(termination(raw))

    def revoked():
        raise PermissionError("revoked before commit")

    with pytest.raises(PermissionError):
        store.terminate(req, "a" * 64, revoked)
    with pytest.raises(LookupError):
        store.read(str(req.termination_id))
    original = g.client.post(
        "/management/v1/runtime-gates",
        headers={**g.headers, "Content-Type": "application/json"},
        content=raw,
    )
    assert original.status_code == 200
    # Fill only this owned database using the real transactional authority.
    for _ in range(128):
        request = GateTerminationCommand.model_validate(termination(json.dumps(command("open")), 1))
        assert (
            store.terminate(request, "b" * 64, lambda: None)["original"]["outcome"]
            == "no_gate_commit"
        )
    assert (
        g.client.post(
            PATH, headers=headers, json=termination(json.dumps(command("open")), 1)
        ).status_code
        == 429
    )
    assert (
        g.client.get(
            PATH, headers={**headers, "X-Runtime-Operation": str(request.termination_id)}
        ).status_code
        == 200
    )
