"""Real scratch PG ownership; provider/Host/S3 transports use existing fixtures."""

import importlib
from hashlib import sha256
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import psycopg
import pytest
from agent_core.application.coverage_executor import observation_id
from agent_core.domain.cloud_artifact_requests import ArtifactMetadataQuery
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.coverage_model_checkpoint import completion_usage, decode_model_checkpoint
from agent_core.domain.coverage_persistence import canonical_coverage_bytes, coverage_result_bytes
from agent_core.domain.coverage_validation import AcceptedCoverageUnit
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import ArtifactId
from agent_core.ports.coverage import CoverageCommit
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_storage.postgres.work_unit import borrow_work_unit

from tests.agent_integrations.test_coverage_model_invocation import invoke
from tests.agent_storage.test_postgres_command_wakeup import (  # noqa: F401
    NAMESPACE,
    dsn,
    postgres_dsn,
)
from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    authority,
    check_authority,
    compose,
)
from tests.worker.coverage_model_cloud_fixtures import model_cloud as cloud_fixture
from tests.worker.test_coverage_model_acceptance import configured


def operation(env):
    name = "agent_storage.postgres.coverage_evidence_operation"
    assert importlib.util.find_spec(name) is not None, "native evidence operation is missing"
    kind = importlib.import_module(name).PostgresCoverageEvidenceOperation
    return kind(env.store, env.cloud.publisher, env.cloud.authority, env.cloud.check_authority)


@pytest.fixture
def model_cloud(dsn):  # noqa: F811
    yield from cloud_fixture.__wrapped__(dsn, SimpleNamespace(param={
        "validation_mode": "final_certification", "runtime": 600,
    }))


@pytest.fixture
def evidence(model_cloud, monkeypatch):  # noqa: F811
    env = model_cloud
    component = compose(env)
    payloads = []

    def interrupted(payload, *, artifact_id):
        payloads.append(payload)
        raise RuntimeError("crash before publication")

    with monkeypatch.context() as patch:
        patch.setattr(env.cloud, "store_payload_immutable", interrupted)
        with pytest.raises(CoverageRefusedError, match="unresolved_failure"):
            invoke(env, component)
    assert len(env.requests) == 1 and len(payloads) == 1
    configured(env)
    env.payload = payloads[0]
    env.checkpoint = decode_model_checkpoint(env.payload.payload)
    counts = completion_usage(env.checkpoint.completion, env.checkpoint.reservation)
    env.receipt = CoverageModelUsageReceipt(
        reservation=env.checkpoint.reservation,
        input_tokens=counts[0], output_tokens=counts[1], total_tokens=counts[2],
        checkpoint_ref=f"artifact://{env.checkpoint.artifact_id}",
        checkpoint_digest=sha256(env.payload.payload).hexdigest(),
    )
    return env


def snapshot(env):
    with psycopg.connect(env.dsn) as connection:
        events = connection.execute(
            "SELECT to_jsonb(e) FROM session_events e WHERE deployment_namespace=%s "
            "AND session_id=%s ORDER BY sequence", (NAMESPACE, env.session),
        ).fetchall()
        budget = connection.execute(
            "SELECT calls,charged_tokens,unresolved FROM coverage_model_ledger "
            "WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s",
            (NAMESPACE, env.binding.namespace, env.binding.run_id),
        ).fetchall()
        units = connection.execute(
            "SELECT ordinal,result FROM coverage_units WHERE deployment_namespace=%s "
            "AND namespace=%s AND run_id=%s ORDER BY ordinal",
            (NAMESPACE, env.binding.namespace, env.binding.run_id),
        ).fetchall()
    return events, budget, units


def metadata(env, identifier=None):
    return env.cloud.metadata.get_metadata(ArtifactMetadataQuery(
        deployment_namespace=NAMESPACE, session_id=env.session,
        artifact_id=identifier or env.checkpoint.artifact_id,
    ))


def checkpoint(env, owner=None):
    return (owner or operation(env)).publish_model_checkpoint(
        env.binding, env.receipt, env.payload, fence=env.fence,
    )


def acceptance(env):
    observation = derive_semantic_observation(
        env.payload.payload, env.receipt, env.definition, env.key, env.record,
    )
    result = AcceptedCoverageUnit(
        key=observation.key, result_digest=observation.digest, outcome=observation.outcome,
    )
    body = coverage_result_bytes((result,))
    digest = sha256(body).hexdigest()
    identifier = ArtifactId(uuid5(NAMESPACE_URL, "evidence-operation:" + digest))
    request = CoverageCommit(
        namespace=env.binding.namespace, run_id=env.binding.run_id,
        session_id=env.session, task_id=env.binding.task_id,
        snapshot_id=env.binding.snapshot.snapshot_id,
        contract_digest=env.binding.contract.digest,
        manifest_digest=env.binding.snapshot.manifest_digest,
        commit_key=str(identifier), result_artifact_ref=f"artifact://{identifier}",
        result_artifact_digest=digest, results=(result,),
    )
    return request, (
        (observation_id(env.binding, env.key), env.payload.model_copy(update={
            "kind": "coverage_observation", "mime_type": "application/octet-stream",
            "payload": canonical_coverage_bytes(observation.model_dump(mode="json")),
        })),
        (identifier, env.payload.model_copy(update={
            "kind": "coverage_results", "mime_type": "application/octet-stream", "payload": body,
        })),
    )


def guard_io(env, monkeypatch):
    calls = []
    for name in ("put_if_absent", "read_version_verified"):
        original = getattr(env.objects, name)

        def monitored(*args, _original=original, _name=name, **kwargs):
            assert borrow_work_unit((env.dsn, NAMESPACE)) is None, "object I/O inside mutation TX"
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(env.objects, name, monitored)
    return calls


def test_checkpoint_atomic_usage_replay_without_locked_io(evidence, monkeypatch):
    env = evidence
    io = guard_io(env, monkeypatch)
    owner = operation(env)
    sequence, body = checkpoint(env, owner)
    assert body == env.payload.payload
    events = env.events.list_for_session(env.session)
    assert events[-1].event_type == EventType.COVERAGE_MODEL_USAGE_RECORDED
    assert events[-1].sequence == sequence
    assert events[-2].event_type == EventType.COVERAGE_ARTIFACT_MATERIALIZED
    assert metadata(env).lifecycle_status == "finalized"
    before = snapshot(env)
    assert before[1] == [(1, 30, 0)]
    assert checkpoint(env, owner) == (sequence, body)
    assert snapshot(env) == before and len(env.requests) == 1
    assert "put_if_absent" in io and "read_version_verified" in io


def test_acceptance_publishes_and_accepts_in_one_owner(evidence, monkeypatch):
    env = evidence
    checkpoint(env)
    request, payloads = acceptance(env)
    guard_io(env, monkeypatch)
    owner = operation(env)
    receipt = owner.commit_evidence(env.binding, request, payloads, fence=env.fence)
    assert env.store.counts(env.binding.namespace, env.binding.run_id) == (2, 1)
    assert all(metadata(env, ident).lifecycle_status == "finalized" for ident, _ in payloads)
    before = snapshot(env)
    assert owner.commit_evidence(env.binding, request, payloads, fence=env.fence) == receipt
    assert snapshot(env) == before and len(env.requests) == 1


@pytest.mark.parametrize("stage", ["upload", "receipt", "usage", "accept"])
def test_fault_rolls_back_all_postupload_mutations(evidence, monkeypatch, stage):
    env = evidence
    if stage == "accept":
        checkpoint(env)
    owner = operation(env)
    request, payloads = acceptance(env)
    from agent_storage.postgres import coverage as commit_module
    from agent_storage.postgres import coverage_artifact_publication as publication_module
    from agent_storage.postgres import coverage_model_budget as budget_module

    target, name = {
        "upload": (env.objects, "put_if_absent"),
        "receipt": (publication_module, "record_receipts"),
        "usage": (budget_module, "project_watermark"),
        "accept": (commit_module, "project_batch"),
    }[stage]
    original = getattr(target, name)
    crashed = []

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        crashed.append(True)
        raise RuntimeError("lost acknowledgement")

    before = snapshot(env)
    with monkeypatch.context() as patch:
        patch.setattr(target, name, crash)
        with pytest.raises(RuntimeError, match="lost acknowledgement"):
            if stage == "accept":
                owner.commit_evidence(env.binding, request, payloads, fence=env.fence)
            else:
                checkpoint(env, owner)
    assert snapshot(env) == before
    assert crashed == [True]
    staged_ids = ([ident for ident, _ in payloads] if stage == "accept"
                  else [env.checkpoint.artifact_id])
    assert all(metadata(env, ident).lifecycle_revision == 0 for ident in staged_ids)
    if stage == "accept":
        owner.commit_evidence(env.binding, request, payloads, fence=env.fence)
    else:
        checkpoint(env, owner)
    assert len(env.requests) == 1 and snapshot(env)[1] == [(1, 30, 0)]


@pytest.mark.parametrize("mutation", ["file_name", "object_version", "retention", "event", "usage"])
def test_final_callback_tampering_rolls_back_full_settlement(evidence, mutation):
    env = evidence
    original = env.cloud.check_authority
    changed = []

    def check():
        original()
        if borrow_work_unit((env.dsn, NAMESPACE)) is None or changed:
            return
        with env.database.connect() as connection:
            row = connection.execute(
                "SELECT sequence FROM session_events WHERE deployment_namespace=%s "
                "AND session_id=%s AND event_type='coverage_model_usage_recorded'",
                (NAMESPACE, env.session),
            ).fetchone()
            if row is None:
                return
            changed.append(True)
            if mutation in {"event", "usage"}:
                kind = ("coverage_artifact_materialized" if mutation == "event"
                        else "coverage_model_usage_recorded")
                connection.execute(
                    "UPDATE session_events SET payload=payload || '{\"tampered\":true}'::jsonb "
                    "WHERE deployment_namespace=%s AND session_id=%s AND event_type=%s",
                    (NAMESPACE, env.session, kind),
                )
            else:
                fragment = {
                    "file_name": "file_name='forged.bin'",
                    "object_version": "object_version='forged-version'",
                    "retention": "retained_until=retained_until+interval '1 second'",
                }[mutation]
                connection.execute(
                    f"UPDATE artifact_payload_metadata SET {fragment} "
                    "WHERE deployment_namespace=%s AND artifact_id=%s",
                    (NAMESPACE, env.checkpoint.artifact_id),
                )

    env.cloud.check_authority = check
    before = snapshot(env)
    with pytest.raises((ValueError, psycopg.Error)):
        checkpoint(env)
    assert changed and snapshot(env) == before
    assert metadata(env).lifecycle_revision == 0


@pytest.mark.parametrize("phase", ["put", "get", "settled"])
def test_host_revocation_at_physical_and_final_boundaries(evidence, monkeypatch, phase):
    env = evidence
    original = env.cloud.check_authority
    revoked = []

    def check():
        original()
        if phase == "settled" and borrow_work_unit((env.dsn, NAMESPACE)) is not None:
            with env.database.connect() as connection:
                settled = connection.execute(
                    "SELECT 1 FROM coverage_model_calls WHERE deployment_namespace=%s "
                    "AND run_id=%s AND receipt IS NOT NULL", (NAMESPACE, env.binding.run_id),
                ).fetchone()
                if settled:
                    revoked.append(True)
        if revoked:
            raise ValueError("Host authority revoked")

    env.cloud.check_authority = check
    if phase != "settled":
        name = "put_if_absent" if phase == "put" else "read_version_verified"
        transport = getattr(env.objects, name)

        def revoke(*args, **kwargs):
            result = transport(*args, **kwargs)
            revoked.append(True)
            return result

        monkeypatch.setattr(env.objects, name, revoke)
    before = snapshot(env)
    with pytest.raises(ValueError, match="Host authority revoked"):
        checkpoint(env)
    assert snapshot(env) == before and revoked
    assert metadata(env).lifecycle_revision == 0
