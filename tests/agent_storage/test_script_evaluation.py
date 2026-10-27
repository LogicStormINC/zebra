"""Disposable PostgreSQL, actual sandbox Eval, atomic registration and no unknown retry."""
# ruff: noqa: F811

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from agent_storage.postgres.script_evaluation import ScriptEvaluationStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.publication_config import load_publication_approval
from zebra_agent_api.script_publication_contract import PATH
from zebra_agent_worker.script_evaluation import run_evaluation

from tests.agent_runtime.test_native_script_eval import suite_for
from tests.api.test_bundle_management import write
from tests.api.test_publication_management import publisher  # noqa: F401
from tests.api.test_script_publication import host_management_dsn, request, scripted  # noqa: F401


def prepared(p, tmp_path, *, expected="hello"):
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as client:
        body = request(p)
        response = client.post(PATH, headers=p.headers, json=body)
        assert response.status_code == 200, response.text
    version = p.registry.get_version(p.scope, UUID(body["versionId"]))
    suite = suite_for(
        version.runtime_assembly,
        definition_id=str(p.scope.definition_id),
        version_id=str(version.version_id),
        definition_digest=version.definition_digest,
        cases=[
            {
                "name": "exact-output",
                "binding": "native.tool",
                "arguments": {"query": "input"},
                "expected": {"value": expected},
            }
        ],
    )
    path = tmp_path / "suite.json"
    write(path, suite.model_dump(mode="json"))
    cfg = replace(p.cfg, runtime=replace(p.cfg.runtime, runtime_class="os-sandbox"))
    store = ScriptEvaluationStore(cfg.database_url, "local")
    store.initialize()
    return cfg, path, suite, store, response.json()["result"]


@pytest.mark.skipif(sys.platform != "darwin", reason="actual Seatbelt evaluator")
@pytest.mark.parametrize("expected,passed", [("hello", True), ("wrong", False)])
def test_actual_evaluator_registers_once_and_d_gate_consumes(scripted, tmp_path, expected, passed):
    p = scripted
    cfg, path, suite, store, materialized = prepared(p, tmp_path, expected=expected)
    operation = uuid4()
    result = run_evaluation(cfg, path, operation)
    assert result["status"] == "completed" and result["summary"]["passed"] is passed
    evidence = p.registry.latest_eval_evidence(p.scope, suite.version_id)
    assert evidence.evidence_id == operation and evidence.passed is passed
    assert evidence.definition_digest == suite.definition_digest
    assert run_evaluation(cfg, path, operation) == result
    assert run_evaluation(cfg, path, operation, mode="read") == result
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
        published = c.post(
            PATH,
            headers=p.headers,
            json={
                "action": "publish",
                "operationId": str(uuid4()),
                "expectedRevision": materialized["revision"],
                "versionId": str(suite.version_id),
                "evidenceId": str(operation),
            },
        )
        assert published.status_code == (200 if passed else 403), published.text
    # An independent interpreter observes the original shared result, never executes a runner.
    code = """import json,os
from pathlib import Path
from zebra_agent_api.publication_config import load_publication_approval
from agent_storage.postgres.script_evaluation import ScriptEvaluationStore
from uuid import UUID
cfg=json.loads(Path(os.environ['EVAL_PRIVATE_TEST']).read_text())
s=ScriptEvaluationStore(cfg['dsn'],'local')
a=load_publication_approval(cfg['approval'],'local')
print(json.dumps(s.observe(a.trust,UUID(cfg['operation']))))"""
    private = tmp_path / "child.json"
    write(private, {"dsn": cfg.database_url, "approval": str(p.path), "operation": str(operation)})
    import os

    output = subprocess.check_output(
        [sys.executable, "-c", code],
        env={**os.environ, "EVAL_PRIVATE_TEST": str(private)},
        text=True,
    )
    assert json.loads(output) == result


def test_concurrent_claim_and_unknown_survive_reopen(scripted, tmp_path):
    p = scripted
    cfg, path, suite, store, _ = prepared(p, tmp_path)
    trust = load_publication_approval(str(p.path), "local").trust
    operation = uuid4()

    def claim(_):
        return ScriptEvaluationStore(cfg.database_url, "local").claim(
            trust, operation, suite.digest, p.scope.scope_key, suite.version_id, lambda: None
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, range(2)))
    assert sorted(first for first, _ in results) == [False, True]
    assert run_evaluation(cfg, path, operation)["status"] == "unknown"
    assert run_evaluation(cfg, path, operation, mode="read")["status"] == "unknown"
    with pytest.raises(ValueError, match="UNKNOWN_BLOCKED"):
        run_evaluation(cfg, path, uuid4())
    assert p.registry.latest_eval_evidence(p.scope, suite.version_id) is None
    with pytest.raises(ValueError, match="CONFLICT"):
        store.claim(
            trust,
            operation,
            "sha256:" + "0" * 64,
            p.scope.scope_key,
            suite.version_id,
            lambda: None,
        )


def test_suite_and_current_approval_changes_refused(scripted, tmp_path):
    p = scripted
    cfg, path, suite, store, _ = prepared(p, tmp_path)
    value = suite.model_dump(mode="json")
    for key, replacement in (
        ("evaluator_actor", "foreign"),
        ("policy_version", "foreign"),
        ("definition_digest", "0" * 64),
    ):
        write(path, value | {key: replacement})
        with pytest.raises(PermissionError):
            run_evaluation(cfg, path, uuid4())
    write(path, value | {"passed": True})
    with pytest.raises(ValueError):
        run_evaluation(cfg, path, uuid4())


@pytest.mark.skipif(sys.platform != "darwin", reason="real sandbox revoke fence")
def test_revocation_after_execution_leaves_unknown_without_evidence(
    scripted, tmp_path, monkeypatch
):
    from agent_runtime.native_script_runtime import ScopedNativeScriptRunner

    p = scripted
    cfg, path, suite, store, _ = prepared(p, tmp_path)
    original = ScopedNativeScriptRunner.run
    calls = []

    def revoke(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        calls.append(True)
        write(p.path, p.approval | {"policy_version": "changed-policy/1"})
        return result

    monkeypatch.setattr(ScopedNativeScriptRunner, "run", revoke)
    operation = uuid4()
    with pytest.raises(PermissionError):
        run_evaluation(cfg, path, operation)
    assert len(calls) == 1
    write(p.path, p.approval)
    assert run_evaluation(cfg, path, operation)["status"] == "unknown"
    assert len(calls) == 1 and p.registry.latest_eval_evidence(p.scope, suite.version_id) is None


def test_independent_processes_only_one_claim(scripted, tmp_path):
    import os

    p = scripted
    cfg, path, suite, store, _ = prepared(p, tmp_path)
    operation = uuid4()
    private = tmp_path / "process-claim.json"
    write(
        private,
        {
            "dsn": cfg.database_url,
            "approval": str(p.path),
            "operation": str(operation),
            "suite": str(path),
        },
    )
    code = """import os,json
from pathlib import Path
from uuid import UUID
from agent_storage.postgres.script_evaluation import ScriptEvaluationStore
from agent_runtime.native_script_eval import ScriptEvalSuite
from zebra_agent_api.publication_config import load_publication_approval
c=json.loads(Path(os.environ['EVAL_CLAIM_TEST']).read_text())
a=load_publication_approval(c['approval'],'local')
s=ScriptEvalSuite.model_validate_json(Path(c['suite']).read_bytes())
store=ScriptEvaluationStore(c['dsn'],'local')
first,result=store.claim(a.trust,UUID(c['operation']),s.digest,a.definition_scope.scope_key,s.version_id,lambda:None)
print(json.dumps({'claimed':first,'status':result['status']}))"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "EVAL_CLAIM_TEST": str(private)},
        )
        for _ in range(2)
    ]
    results = []
    for child in children:
        out, err = child.communicate(timeout=20)
        assert child.returncode == 0, err.decode()
        results.append(json.loads(out))
    assert sorted(r["claimed"] for r in results) == [False, True]
    assert all(r["status"] == "unknown" for r in results)
    assert run_evaluation(cfg, path, operation)["status"] == "unknown"
