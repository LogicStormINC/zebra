"""Run with pytest; real SQLite Artifacts, test-only execution index, no services."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agent_core.application.coverage_checks import PublishedCoverageRunner
from agent_core.application.coverage_executor import CoverageExecutor, observation_id
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.coverage_contracts import (
    CoverageContract,
    CoverageRefusalReason,
    CoverageRefusedError,
    CoverageScope,
)
from agent_core.domain.coverage_execution import CoverageExecutionBudget, PublishedCoverageCheck
from agent_core.domain.coverage_persistence import (
    CoverageRunBinding,
    coverage_manifest_bytes,
    coverage_result_bytes,
)
from agent_core.domain.coverage_snapshot import (
    CoveragePart,
    CoveragePartRead,
    CoverageRecord,
    CoverageSnapshot,
)
from agent_core.domain.coverage_validation import expected_units, manifest_digest
from agent_core.domain.identifiers import ArtifactId, SessionId, TaskId
from agent_core.domain.leases import LeaseFence, LeaseLostError
from agent_core.ports.coverage import CoverageCommitReceipt
from agent_storage import SQLiteArtifactPayloadStore

NOW = datetime(2026, 10, 8, tzinfo=UTC)


class ExecutionIndex:
    """Test double only: retained between fresh executors, never a production fallback."""

    def __init__(self, binding, records, artifacts, fence):
        self.binding, self.artifacts, self.fence = binding, artifacts, fence
        self.units = expected_units(binding.contract, records)
        self.accepted = {}
        self.receipts = {}
        self.attempts = []
        self.policy = None
        self.pages = []
        self.bound = False
        self.lose_response = False

    def guard(self, namespace, run_id, fence=None):
        assert (namespace, run_id) == (self.binding.namespace, self.binding.run_id)
        if fence is not None and fence != self.fence:
            raise LeaseLostError("stale test fence")

    def bind(self, binding, *, fence):
        self.guard(binding.namespace, binding.run_id, fence)
        assert binding == self.binding
        self.bound = True
        return 1

    def missing_units(self, namespace, run_id, *, limit=100, after_ordinal=-1):
        self.guard(namespace, run_id)
        assert self.bound and 1 <= limit <= 1000
        page = tuple(
            (i, k) for i, k in enumerate(self.units) if i > after_ordinal and k not in self.accepted
        )[:limit]
        self.pages.append(page)
        return page

    def accepted_for_record(self, namespace, run_id, record_id, *, check_id=None):
        self.guard(namespace, run_id)
        return tuple(
            v
            for k, v in self.accepted.items()
            if k.record_id == record_id and (check_id is None or k.check_id == check_id)
        )

    def reserve_attempt(self, binding, key, *, input_bytes, budget, fence):
        self.guard(binding.namespace, binding.run_id, fence)
        assert binding == self.binding and key in self.units and key not in self.accepted
        if self.policy is not None and self.policy != budget:
            raise ValueError("coverage budget cannot change on restart")
        if (
            len(self.attempts) >= budget.max_attempts
            or sum(self.attempts) + input_bytes > budget.max_input_bytes
        ):
            raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)
        self.policy = budget
        self.attempts.append(input_bytes)
        return len(self.attempts)

    def commit(self, request, *, fence):
        self.guard(request.namespace, request.run_id, fence)
        identifier = ArtifactId(UUID(request.result_artifact_ref.removeprefix("artifact://")))
        body = self.artifacts.read_payload_bytes(identifier)
        assert sha256(body).hexdigest() == request.result_artifact_digest
        assert body == coverage_result_bytes(request.results)
        assert all(r.key in self.units and r.key not in self.accepted for r in request.results)
        self.accepted.update((r.key, r) for r in request.results)
        receipt = CoverageCommitReceipt(
            namespace=request.namespace,
            run_id=request.run_id,
            commit_key=request.commit_key,
            result_artifact_digest=request.result_artifact_digest,
            event_watermark=len(self.receipts) + 1,
            committed_at=NOW,
        )
        self.receipts[request.commit_key] = receipt
        if self.lose_response:
            self.lose_response = False
            raise RuntimeError("lost commit response")
        return receipt

    def counts(self, namespace, run_id):
        self.guard(namespace, run_id)
        return len(self.units), len(self.accepted)


def setup_execution(tmp_path, *, bodies=(("risk α", "safe"),), model=None):
    definition = PublishedCoverageCheck(
        id="risk",
        version="1",
        kind="program" if model is None else "model",
        implementation="literal_contains/1" if model is None else "structured_model/1",
        terms=("risk",) if model is None else (),
        model_profile=None if model is None else "test-profile",
        instructions="" if model is None else "Return an exact structured observation",
    )
    spec = CoverageContract(
        scope=CoverageScope(
            timezone="UTC", from_inclusive=NOW, to_exclusive=NOW + timedelta(days=1)
        ),
        checks=(definition.contract_check,),
    )
    session = SessionId(uuid4())
    artifacts = SQLiteArtifactPayloadStore(tmp_path / "coverage.db")
    refs, rows = {}, []
    # Reuse identical source bytes across large manifests; record identity stays exact.
    payload_refs = {}
    for i, parts in enumerate(bodies):
        canonical = tuple(
            CoveragePart(
                id=f"part-{j}",
                digest=sha256(body.encode()).hexdigest(),
                byte_length=len(body.encode()),
            )
            for j, body in enumerate(parts)
        )
        row = CoverageRecord(
            ordinal=i,
            record_id=f"record-{i}",
            content_digest=sha256(json.dumps(parts).encode()).hexdigest(),
            parts=canonical,
        )
        rows.append(row)
        for part, body in zip(canonical, parts, strict=True):
            if body not in payload_refs:
                payload_refs[body] = artifacts.store_payload(
                    ArtifactPayloadWrite(
                        session_id=session,
                        kind="canonical_body",
                        mime_type="text/plain",
                        payload=body.encode(),
                        created_at=NOW,
                    )
                ).uri
            refs[row.record_id, part.id] = payload_refs[body]
    records = tuple(rows)
    manifest = coverage_manifest_bytes(records)
    uri = artifacts.store_payload(
        ArtifactPayloadWrite(
            session_id=session,
            kind="coverage_manifest",
            mime_type="application/json",
            payload=manifest,
            created_at=NOW,
        )
    ).uri
    snapshot = CoverageSnapshot(
        namespace="test-tenant",
        host_id="trench",
        snapshot_id="snapshot",
        authority_revision="grant-1",
        contract_digest=spec.digest,
        scope_digest=spec.scope.digest,
        manifest_digest=manifest_digest(spec, records),
        record_count=len(records),
        manifest_artifact_ref=uri,
        as_of=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    binding = CoverageRunBinding(
        namespace=snapshot.namespace,
        session_id=session,
        task_id=TaskId(uuid4()),
        run_id="run",
        contract=spec,
        snapshot=snapshot,
        manifest_artifact_digest=sha256(manifest).hexdigest(),
    )
    fence = LeaseFence(control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="test")
    env = SimpleNamespace(
        binding=binding,
        records=records,
        artifacts=artifacts,
        refs=refs,
        fence=fence,
        runner=PublishedCoverageRunner((definition,), model=model),
        budget=CoverageExecutionBudget(max_attempts=100_000, max_input_bytes=100_000_000),
        clock=NOW,
        revoked=False,
        reads=[],
    )
    env.store = ExecutionIndex(binding, records, artifacts, fence)
    return env


def executor(env, **overrides):
    def authority():
        if env.revoked:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    def read(record, part):
        env.reads.append((record.record_id, part.id))
        return CoveragePartRead(
            namespace=env.binding.namespace,
            snapshot_id=env.binding.snapshot.snapshot_id,
            record_id=record.record_id,
            content_digest=record.content_digest,
            part=part,
            artifact_ref=env.refs[record.record_id, part.id],
        )

    return CoverageExecutor(
        **(
            {
                "binding": env.binding,
                "records": env.records,
                "store": env.store,
                "artifacts": env.artifacts,
                "read": read,
                "runner": env.runner,
                "budget": env.budget,
                "check_authority": authority,
                "now": lambda: env.clock,
            }
            | overrides
        )
    )


def test_parts_before_merge_and_finding_includes_negative_part(tmp_path):
    env = setup_execution(tmp_path)
    run = executor(env)
    assert run.execute_batch(fence=env.fence, limit=1) == (3, 1)
    assert run.execute_batch(fence=env.fence, limit=1) == (3, 2)
    assert [v.outcome for v in env.store.accepted.values()] == ["finding", "clear"]
    assert all(k.kind == "part" for k in env.store.accepted)
    assert run.execute_batch(fence=env.fence, limit=1) == (3, 3)
    merged = tuple(env.store.accepted.values())[-1]
    assert merged.key.kind == "record_merge" and merged.outcome == "finding"
    payload = env.artifacts.read_payload_bytes(observation_id(env.binding, merged.key))
    assert json.loads(payload)["quotes"] == [
        {"part_id": "part-0", "start": 0, "end": 4, "text": "risk"}
    ]
    assert run.execute_batch(fence=env.fence) == (3, 3)
    assert len(env.store.attempts) == len(env.store.receipts) == 3


def test_multipart_memory_bound_refuses_before_body_or_prior_reads(tmp_path, monkeypatch):
    env = setup_execution(tmp_path)
    run = executor(env)
    run.execute_batch(fence=env.fence, limit=2)
    env.reads.clear()
    # Two valid individually bounded parts can still exceed the merge heap budget.
    monkeypatch.setattr("agent_core.application.coverage_executor.MAX_BYTES", 8)
    monkeypatch.setattr(run, "_prior", lambda *_: pytest.fail("prior read before bound"))
    attempts = len(env.store.attempts)
    with pytest.raises(CoverageRefusedError) as error:
        run.execute_batch(fence=env.fence)
    assert error.value.reason == CoverageRefusalReason.BUDGET_EXCEEDED
    assert env.reads == [] and len(env.store.attempts) == attempts


def test_merge_prior_observations_have_an_aggregate_bound(tmp_path, monkeypatch):
    env = setup_execution(tmp_path)
    run = executor(env)
    run.execute_batch(fence=env.fence, limit=2)
    sizes = [
        len(run._bytes(f"artifact://{observation_id(env.binding, item.key)}"))
        for item in env.store.accepted.values()
    ]
    monkeypatch.setattr("agent_core.application.coverage_executor.MAX_BYTES", max(sizes))
    with pytest.raises(CoverageRefusedError):
        run._prior(env.store.units[-1], env.records[0])


def test_executor_refuses_unpublishable_count_before_storage_reads(tmp_path, monkeypatch):
    env = setup_execution(tmp_path)
    monkeypatch.setattr("agent_core.application.coverage_executor.MAX_UNITS", 2)
    monkeypatch.setattr(
        CoverageExecutor, "_bytes", lambda *_: pytest.fail("manifest read before count bound")
    )
    with pytest.raises(CoverageRefusedError):
        executor(env)
    assert not env.store.attempts and not env.reads


def test_merge_before_all_parts_is_rejected(tmp_path, monkeypatch):
    env = setup_execution(tmp_path)
    monkeypatch.setattr(env.store, "missing_units", lambda *a, **kw: ((2, env.store.units[2]),))
    with pytest.raises(ValueError, match="before every matching part"):
        executor(env).execute_batch(fence=env.fence)
    assert not env.store.accepted and not env.store.attempts and not env.reads


def test_all_negative_and_empty_counts(tmp_path):
    env = setup_execution(tmp_path, bodies=(("safe", "also safe"),))
    assert executor(env).execute_batch(fence=env.fence) == (3, 3)
    assert {r.outcome for r in env.store.accepted.values()} == {"clear"}
    empty = setup_execution(tmp_path / "empty", bodies=())
    assert executor(empty).execute_batch(fence=empty.fence) == (0, 0)
    assert not empty.store.attempts and not empty.reads and not empty.store.receipts


@pytest.mark.parametrize("failure", ["lost_commit_response", "after_observation"])
def test_fresh_executor_recovers_without_rerunning_model(tmp_path, monkeypatch, failure):
    calls = []

    def model(definition, key, bodies):
        calls.append(key)
        return {"key": key.model_dump(mode="json"), "outcome": "clear", "summary": "checked"}

    env = setup_execution(tmp_path, bodies=(("safe",),), model=model)
    if failure == "lost_commit_response":
        env.store.lose_response = True
    else:
        original = env.artifacts.store_payload_immutable

        def crash(payload, *, artifact_id):
            result = original(payload, artifact_id=artifact_id)
            if payload.kind == "coverage_observation":
                raise RuntimeError("crash after observation Artifact")
            return result

        monkeypatch.setattr(env.artifacts, "store_payload_immutable", crash)
    with pytest.raises(RuntimeError, match="lost commit response|crash after observation"):
        executor(env).execute_batch(fence=env.fence, limit=1)
    assert len(calls) == 1
    assert len(env.store.accepted) == (1 if failure == "lost_commit_response" else 0)
    assert env.artifacts.get_payload(observation_id(env.binding, calls[0])) is not None
    env.artifacts = SQLiteArtifactPayloadStore(tmp_path / "coverage.db")
    env.store.artifacts = env.artifacts
    assert executor(env).execute_batch(fence=env.fence) == (2, 2)
    assert calls == [env.store.units[0]]
    assert len(env.store.receipts) == 2
    assert len(env.store.attempts) == (2 if failure == "lost_commit_response" else 3)


@pytest.mark.parametrize(
    "budget",
    [
        CoverageExecutionBudget(max_attempts=1, max_input_bytes=100),
        CoverageExecutionBudget(max_attempts=100, max_input_bytes=4),
    ],
)
def test_budget_survives_fresh_executor(tmp_path, budget):
    env = setup_execution(tmp_path, bodies=(("safe",),))
    env.budget = budget
    assert executor(env).execute_batch(fence=env.fence, limit=1) == (2, 1)
    with pytest.raises(CoverageRefusedError, match="budget_exceeded"):
        executor(env).execute_batch(fence=env.fence)
    assert len(env.store.accepted) == len(env.store.attempts) == 1


@pytest.mark.parametrize("invalid", ["key", "quote", "other_part", "no_evidence", "extra"])
def test_invalid_model_output_never_counts(tmp_path, invalid):
    def model(definition, key, bodies):
        result = {
            "key": key.model_dump(mode="json"),
            "outcome": "finding",
            "summary": "risk",
            "quotes": [{"part_id": key.part_id, "start": 0, "end": 4, "text": "risk"}],
        }
        if invalid == "key":
            result["key"]["record_id"] = "invented"
        elif invalid == "quote":
            result["quotes"][0]["text"] = "fake"
        elif invalid == "other_part":
            result["quotes"][0]["part_id"] = "part-1"
        elif invalid == "no_evidence":
            result["quotes"] = []
        else:
            result["complete"] = True
        return result

    env = setup_execution(tmp_path, model=model)
    with pytest.raises(ValueError):
        executor(env).execute_batch(fence=env.fence, limit=1)
    assert not env.store.accepted and not env.store.receipts
    assert env.artifacts.get_payload(observation_id(env.binding, env.store.units[0])) is None


@pytest.mark.parametrize("failure", ["revocation", "expiry", "fence"])
@pytest.mark.parametrize("stage", ["before", "after_model"])
def test_authority_expiry_and_stale_fence_never_count(tmp_path, failure, stage):
    def invalidate():
        if failure == "revocation":
            env.revoked = True
        elif failure == "expiry":
            env.clock = env.binding.snapshot.expires_at
        else:
            env.store.fence = env.fence.model_copy(update={"fencing_token": 2})

    calls = []

    def model(definition, key, bodies):
        calls.append(key)
        invalidate()
        return {"key": key.model_dump(mode="json"), "outcome": "clear", "summary": "checked"}

    env = setup_execution(tmp_path, bodies=(("safe",),), model=model)
    if stage == "before":
        invalidate()
    with pytest.raises((CoverageRefusedError, LeaseLostError)):
        executor(env).execute_batch(fence=env.fence, limit=1)
    assert not env.store.accepted and not env.store.receipts
    assert len(calls) == (0 if stage == "before" else 1)


def test_failed_model_attempt_consumes_budget_across_restart(tmp_path):
    calls = []

    def model(definition, key, bodies):
        calls.append(key)
        raise RuntimeError("model unavailable")

    env = setup_execution(tmp_path, bodies=(("safe",),), model=model)
    env.budget = CoverageExecutionBudget(max_attempts=1, max_input_bytes=100)
    with pytest.raises(RuntimeError, match="model unavailable"):
        executor(env).execute_batch(fence=env.fence, limit=1)
    with pytest.raises(CoverageRefusedError, match="budget_exceeded"):
        executor(env).execute_batch(fence=env.fence, limit=1)
    assert calls == [env.store.units[0]]
    assert env.store.attempts == [4] and not env.store.accepted


@pytest.mark.parametrize("failure", ["definition", "version", "no_model", "oversize"])
def test_runner_refuses_unsupported_check_without_model_call(tmp_path, failure):
    calls = []

    def model(definition, key, bodies):
        calls.append(key)
        raise AssertionError("unsupported check must not invoke the model")

    env = setup_execution(tmp_path, bodies=(("safe",),), model=model)
    definition = next(iter(env.runner.definitions.values()))
    if failure == "definition":
        definition = definition.model_copy(update={"instructions": "changed definition"})
    elif failure == "version":
        definition = definition.model_copy(update={"version": "2"})
    elif failure == "oversize":
        definition = definition.model_copy(update={"max_part_characters": 3})
    runner = PublishedCoverageRunner((definition,), model=None if failure == "no_model" else model)
    if failure == "oversize":
        # Bind the changed definition so this exercises the input ceiling, not drift.
        key = env.store.units[0].model_copy(
            update={
                "definition_digest": definition.contract_check.definition_digest,
            }
        )
        with pytest.raises(CoverageRefusedError, match="coverage_unsupported"):
            runner.run(key, {"part-0": "safe"}, prior=())
    else:
        with pytest.raises(CoverageRefusedError, match="coverage_unsupported"):
            executor(env, runner=runner).execute_batch(fence=env.fence, limit=1)
    assert not calls and not env.store.accepted and not env.store.receipts


def test_large_10003_manifest_executes_only_bounded_batch(tmp_path):
    env = setup_execution(tmp_path, bodies=(("safe",),) * 10_003)
    run = executor(env)
    assert run.execute_batch(fence=env.fence, limit=7) == (20_006, 7)
    assert len(env.store.pages[-1]) == len(env.store.attempts) == 7
    assert len(env.store.receipts) == 7 and len(env.reads) == 7
    assert {k.record_id for k in env.store.accepted} == {f"record-{i}" for i in range(4)}
    assert run.execute_batch(fence=env.fence, limit=7) == (20_006, 14)
    tail = env.store.missing_units(
        env.binding.namespace, env.binding.run_id, limit=7, after_ordinal=20_001
    )
    assert len(tail) == 4 and tail[-1][1].record_id == "record-10002"
