"""Real PG authority/resource fencing; no fabricated passing Eval or engine proof."""

# ruff: noqa: F401,F811
from dataclasses import replace
from uuid import uuid4

import pytest
from agent_core.domain.runtime_gates import GateCommand
from agent_storage import bootstrap_control_plane_epoch
from agent_storage.postgres.agent_registry import AgentDefinitionEvalEvidence
from agent_storage.postgres.epoch import PostgresControlPlaneEpochError, read_control_plane_epoch
from agent_storage.postgres.host_management import HostManagementUnavailable
from agent_storage.postgres.runtime_gates import RuntimeGateStore
from agent_storage.postgres.script_eval_instances import (
    PostgresScriptEvalInstances,
    require_eval_resources_settled,
    require_no_cloud_eval,
)
from zebra_agent_api.publication_config import load_publication_approval

from tests.agent_storage.test_script_evaluation import prepared
from tests.api.test_bundle_management import write
from tests.api.test_publication_management import publisher
from tests.api.test_script_publication import host_management_dsn, scripted


def test_cloud_eval_original_blocks_stop_and_exact_resources_survive_revocation(scripted, tmp_path):
    p = scripted
    cfg, path, suite, store, _ = prepared(p, tmp_path)
    try:
        read_control_plane_epoch(cfg.database_url, deployment_namespace="local")
    except PostgresControlPlaneEpochError:
        bootstrap_control_plane_epoch(cfg.database_url, deployment_namespace="local")
    trust = load_publication_approval(str(p.path), "local").trust
    gate = RuntimeGateStore(cfg.database_url, suite.scope, trust)
    gate.initialize()
    op = uuid4()
    assert store.claim(
        trust,
        op,
        suite.digest,
        p.scope.scope_key,
        suite.version_id,
        lambda: None,
        cloud_instances=True,
    )[0]
    with pytest.raises(HostManagementUnavailable, match="CLOUD_EVAL_SOURCE_INCOMPLETE"):
        gate.read()
    gate.change(
        GateCommand(operation_id=uuid4(), action="drain", expected_revision=0),
        "a" * 64,
        lambda: None,
    )
    with pytest.raises(HostManagementUnavailable, match="CLOUD_EVAL_SOURCE_INCOMPLETE"):
        gate.read()
    # No business Task or WorkerLease is invented to make Eval appear drained.
    with store.database.connect() as c:
        assert c.execute("SELECT count(*) AS n FROM worker_leases").fetchone()["n"] == 0
        with pytest.raises(HostManagementUnavailable, match="CLOUD_EVAL_SOURCE_INCOMPLETE"):
            require_no_cloud_eval(c, "local")
    instance = PostgresScriptEvalInstances(store, trust, op, suite.digest, "e" * 64)
    one = str(uuid4())
    with pytest.raises(ValueError, match="differs"):
        instance.reserve(one, str(uuid4()), "a" * 64)
    labels = instance.reserve(one, str(op), "a" * 64)
    assert labels["zebra.agent.eval-operation"] == str(op)
    cid = "c" * 64
    instance.created(one, cid)
    instance.authorize(one, cid)
    with store.database.connect() as c:
        with pytest.raises(HostManagementUnavailable, match="EVAL_RESOURCE_UNKNOWN"):
            require_eval_resources_settled(c, "local", trust.host_app_id, op)
    # Storage-only negative evidence; this is not an executed/passing Eval claim.
    evidence = AgentDefinitionEvalEvidence(
        authority_issuer=suite.scope.authority_issuer,
        namespace_id=suite.scope.namespace_id,
        definition_id=suite.definition_id,
        version_id=suite.version_id,
        evidence_id=op,
        definition_digest=suite.definition_digest,
        passed=False,
        evaluator_actor=suite.evaluator_actor,
        case_summary={"policy_version": suite.policy_version, "passed": False},
    )
    with pytest.raises(HostManagementUnavailable, match="EVAL_RESOURCE_UNKNOWN"):
        store.complete(trust, op, suite.digest, evidence, {"passed": False}, lambda: None)
    wrong = PostgresScriptEvalInstances(store, trust, op, suite.digest, "f" * 64)
    with pytest.raises(ValueError, match="ownership"):
        wrong.authorize(one, cid)
    current = replace(trust, revision=trust.revision + 1, fingerprint="b" * 64)
    store.approvals.approve(current, trust.revision)
    with pytest.raises(HostManagementUnavailable):
        instance.authorize(one, cid)
    instance.removed(one, cid)  # A late exact deletion fact is retained, not execution authority.
    with store.database.connect() as c:
        require_eval_resources_settled(c, "local", trust.host_app_id, op)
        assert [
            r["status"]
            for r in c.execute(
                "SELECT status FROM native_script_eval_instance_events ORDER BY occurred_at"
            ).fetchall()
        ] == ["reserved", "created", "removed"]
        with pytest.raises(HostManagementUnavailable):
            require_no_cloud_eval(c, "local")  # Settled resource alone does not complete Eval.
    with pytest.raises(ValueError, match="conflicts"):
        instance.created(one, cid)
    result = store.complete(current, op, suite.digest, evidence, {"passed": False}, lambda: None)
    assert result["status"] == "completed" and result["summary"]["passed"] is False
    with store.database.connect() as c:
        require_no_cloud_eval(c, "local")
    assert store.observe(current, op) == result
    fresh = PostgresScriptEvalInstances(store, current, op, suite.digest, "e" * 64)
    with pytest.raises(HostManagementUnavailable, match="NOT_ACTIVE"):
        fresh.reserve(str(uuid4()), str(op), "a" * 64)


def test_closed_admission_refuses_new_cloud_eval_before_original_claim(scripted, tmp_path):
    p = scripted
    cfg, _, suite, store, _ = prepared(p, tmp_path)
    try:
        read_control_plane_epoch(cfg.database_url, deployment_namespace="local")
    except PostgresControlPlaneEpochError:
        bootstrap_control_plane_epoch(cfg.database_url, deployment_namespace="local")
    trust = load_publication_approval(str(p.path), "local").trust
    with store.database.connect() as c:
        c.execute("UPDATE runtime_namespace_gates SET mode='draining'")
    op = uuid4()
    with pytest.raises(ValueError, match="EVAL_ADMISSION_CLOSED"):
        store.claim(
            trust,
            op,
            suite.digest,
            p.scope.scope_key,
            suite.version_id,
            lambda: None,
            cloud_instances=True,
        )
    assert store.observe(trust, op) is None
