"""Linear phase-local source scans, bounded preflight and exact retention merging."""

from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from agent_core.domain.coverage_validation import expected_units
from agent_storage.postgres import coverage_model_acceptance as acceptance
from agent_storage.postgres import coverage_model_verification as verification
from agent_storage.postgres import coverage_publication as publication
from agent_storage.postgres.coverage_artifacts import MAX_COVERAGE_ARTIFACT_BYTES
from agent_storage.postgres.coverage_model_verification import _ModelVerification
from agent_storage.postgres.coverage_publication import CoveragePublicationQueries

from tests.agent_core.test_coverage_contracts import contract, records


def phase(monkeypatch, count=10, *, size=1, duplicate=False):
    counts = Counter()
    policy = SimpleNamespace(model_profile="fixture")
    binding = SimpleNamespace(
        session_id="session",
        namespace="namespace",
        run_id="run",
        contract=SimpleNamespace(checks=("check",), digest=contract().digest),
        snapshot=SimpleNamespace(manifest_artifact_ref="manifest"),
        manifest_artifact_digest="digest",
    )
    keys = tuple(range(count))
    duplicate_key = expected_units(contract(), records())[0]
    requests = {
        i: SimpleNamespace(
            results=(),
            result_artifact_ref=str(i),
            result_artifact_digest="digest",
        )
        for i in keys
    }

    class Connection:
        def execute(self, sql, params):
            assert "coverage_batch_accepted" in sql
            counts["page"] += 1
            return SimpleNamespace(
                fetchall=lambda: [
                    {
                        "sequence": i,
                        "payload": {
                            "request": {
                                "result_artifact_ref": str(i),
                                "result_artifact_digest": "digest",
                            }
                        },
                    }
                    for i in keys
                    if i > params[-1]
                ][:100]
            )

    def manifest(*_):
        counts["manifest"] += 1
        return ()

    def ledger(*args, **kwargs):
        counts["ledger"] += 1
        assert kwargs["_policy"] is policy
        return object(), {}

    def pin(*args):
        counts["pin"] += 1
        return 1 if args[4] == "manifest" else size

    def replay(_, __, event):
        counts["batch"] += 1
        assert counts["pin"] >= counts["batch"] + 1
        request = requests[event.sequence]
        if duplicate:
            request.results = (SimpleNamespace(key=duplicate_key),)
        return request

    def result(*_):
        counts["request"] += 1

    def native_policy(*_):
        counts["policy"] += 1
        return policy

    monkeypatch.setattr(verification, "task_policy", native_policy)
    monkeypatch.setattr(
        verification, "semantic_check", lambda *_: SimpleNamespace(contract_check="check")
    )
    monkeypatch.setattr(verification, "read_manifest", manifest)
    monkeypatch.setattr(verification, "replay_model", ledger)
    monkeypatch.setattr(verification, "expected_units", lambda *_: ())
    monkeypatch.setattr(
        verification,
        "SessionEvent",
        SimpleNamespace(model_validate=lambda row: SimpleNamespace(**row)),
    )
    monkeypatch.setattr(verification, "replay_request", replay)
    monkeypatch.setattr(acceptance, "pin_evidence", pin)
    monkeypatch.setattr(acceptance, "verify_results", result)
    monkeypatch.setattr(
        acceptance, "check_checkpoint_retention", lambda *_: counts.update(retention=1)
    )
    return Connection(), binding, counts


@pytest.mark.parametrize("count", [0, 1, 10, 99, 100, 101, 199, 200, 1000])
def test_publication_real_verifier_replays_ledger_once_per_phase(monkeypatch, count):
    connection, binding, counts = phase(monkeypatch, count)
    store = CoveragePublicationQueries()
    store._deployment, store._artifacts, store._model_observation_deriver = (
        "deployment",
        object(),
        lambda *_: None,
    )
    store._verify_result_sources(connection, binding, ())
    assert counts["manifest"] == counts["ledger"] == 1
    assert counts["policy"] == 1
    assert counts["batch"] == counts["request"] == counts["retention"] == count
    assert counts["page"] == count // 100 + 1
    store._verify_result_sources(connection, binding, ())
    assert counts["ledger"] == counts["manifest"] == 2
    assert counts["policy"] == 2


@pytest.mark.parametrize("scoped", [False, True])
def test_final_lifecycle_uses_one_full_verifier_but_next_phase_is_fresh(monkeypatch, scoped):
    connection, binding, counts = phase(monkeypatch, count=2)
    now = datetime.now(UTC)
    binding.snapshot.as_of = now - timedelta(seconds=1)
    binding.snapshot.expires_at = now + timedelta(hours=1)
    execute = connection.execute

    def query(sql, params=None):
        if "coverage_batch_accepted" in sql:
            return execute(sql, params)
        if "coverage_runs" in sql:
            return SimpleNamespace(fetchone=lambda: {"cancelled": False})
        if "clock_timestamp" in sql:
            return SimpleNamespace(fetchone=lambda: {"now": now})
        if "coverage_report_certified" in sql:
            return SimpleNamespace(fetchall=lambda: [])
        if "session_cancelled" in sql:
            return SimpleNamespace(fetchone=lambda: None)
        pytest.fail(f"unexpected lifecycle SQL: {sql}")

    monkeypatch.setattr(connection, "execute", query)
    monkeypatch.setattr(publication, "assert_projection", lambda *_: None)
    store = CoveragePublicationQueries()
    store._deployment, store._artifacts, store._model_observation_deriver = (
        "deployment", object(), lambda *_: None,
    )
    readers, active = [], []

    @contextmanager
    def scope(*args, **kwargs):
        assert args == (connection, "deployment", binding)
        assert kwargs == {"derive": store._model_observation_deriver, "final_certification": True}
        reader = object()
        readers.append(reader)
        active.append(reader)
        try:
            yield reader
        finally:
            active.clear()

    if scoped:
        store._artifacts = SimpleNamespace(_locked_proof_scope=scope)

    def check_reader(reader):
        assert reader is (active[0] if scoped else store._artifacts)

    def budget(*_, **kwargs):
        check_reader(kwargs["artifacts"])

    def pin(*args):
        check_reader(args[3])
        return 1

    original = store._verify_result_sources

    def verify(*args, **kwargs):
        check_reader(kwargs["artifacts"])
        transcript = original(*args, **kwargs)
        check_reader(transcript.artifacts)
        return transcript

    monkeypatch.setattr(publication, "certify_model_budget", budget)
    monkeypatch.setattr(publication, "pin_evidence", pin)
    monkeypatch.setattr(store, "_verify_result_sources", verify)
    monkeypatch.setattr(store, "_accepted_results", lambda *_: ())
    for number in (1, 2):
        store._check_publication_lifecycle(connection, binding, "report", "digest", [])
        assert counts["policy"] == counts["ledger"] == counts["manifest"] == number
        assert counts["batch"] == counts["request"] == 2 * number
        assert counts["retention"] == 3 * number  # Each batch plus aggregate proof.
        assert not active
    if scoped:
        assert len(readers) == 2 and readers[0] is not readers[1]


def test_size_preflight_refuses_before_canonical_payload_read(monkeypatch):
    connection, binding, counts = phase(monkeypatch, size=MAX_COVERAGE_ARTIFACT_BYTES)
    transcript = _ModelVerification(
        connection, "deployment", binding, artifacts=object(), derive=lambda *_: None
    )
    with pytest.raises(ValueError, match="cumulative"):
        transcript.batches()
    assert not counts["batch"]


def test_batch_cache_retention_merges_minimum_not_first_appended(monkeypatch):
    connection, binding, _ = phase(monkeypatch)
    transcript = _ModelVerification(
        connection, "deployment", binding, artifacts=object(), derive=lambda *_: None
    )
    now = datetime.now(UTC)
    transcript.deadlines[:] = [now + timedelta(seconds=30)]
    existing = [now + timedelta(seconds=10)]
    transcript.merge_deadlines(existing)
    assert existing == [now + timedelta(seconds=10)]
    transcript.batches()
    transcript.deadlines[:] = [now - timedelta(seconds=1)]
    transcript.batches()
    transcript.merge_deadlines(existing)
    assert existing == [now - timedelta(seconds=1)]


def test_duplicate_sources_refuse_during_index_not_after_all_batches(monkeypatch):
    connection, binding, counts = phase(monkeypatch, count=1000, duplicate=True)
    transcript = _ModelVerification(
        connection, "deployment", binding, artifacts=object(), derive=lambda *_: None
    )
    with pytest.raises(ValueError, match="duplicate source"):
        transcript.batches()
    assert counts["batch"] == 2 and transcript._batches is None


def test_individually_bounded_verifies_do_not_accumulate_logical_charge(monkeypatch):
    connection, binding, counts = phase(monkeypatch, count=1, size=MAX_COVERAGE_ARTIFACT_BYTES // 2)
    transcript = _ModelVerification(
        connection, "deployment", binding, artifacts=object(), derive=lambda *_: None
    )
    _, request, _ = transcript.batches()[0]
    for _ in range(3):
        transcript.verify((), request=request, deadlines=[])
    assert counts["request"] == 3 and counts["ledger"] == 1


def test_recovery_transcript_exposes_one_exact_replay_and_merges_retention(monkeypatch):
    connection, binding, counts = phase(monkeypatch, count=1)
    keys = set(expected_units(contract(), records()))
    state = SimpleNamespace(unresolved=0)
    calls = {}
    deadline = datetime.now(UTC) + timedelta(seconds=10)
    monkeypatch.setattr(verification, "read_manifest", lambda *_: records())
    monkeypatch.setattr(verification, "expected_units", lambda *_: tuple(keys))

    def replay(*args, **kwargs):
        counts["ledger"] += 1
        assert kwargs["source_keys"] == keys
        kwargs["retention_deadlines"].append(deadline)
        return state, calls

    monkeypatch.setattr(verification, "replay_model", replay)
    transcript = _ModelVerification(
        connection,
        "deployment",
        binding,
        artifacts=object(),
        derive=lambda *_: None,
        _recovery=True,
    )
    assert transcript.state is state and transcript.calls is calls
    deadlines = [deadline + timedelta(seconds=10)]
    transcript.merge_deadlines(deadlines)
    transcript.verify((), deadlines=deadlines)
    _, request, _ = transcript.batches()[0]
    transcript.verify((), request=request, deadlines=deadlines, before_sequence=10)
    assert counts["ledger"] == 1 and deadlines == [deadline]


def test_uninitialized_recovery_cannot_verify_even_empty_or_supplied_results(monkeypatch):
    connection, binding, counts = phase(monkeypatch)
    monkeypatch.setattr(verification, "replay_model", lambda *_, **__: (None, {}))
    with pytest.raises(ValueError, match="no initialized receipt"):
        _ModelVerification(
            connection, "deployment", binding, artifacts=object(), derive=lambda *_: None
        )
    transcript = _ModelVerification(
        connection,
        "deployment",
        binding,
        artifacts=object(),
        derive=lambda *_: None,
        _recovery=True,
    )
    assert transcript.state is None and transcript.calls == {}
    for results in ((), (SimpleNamespace(key="forged"),)):
        with pytest.raises(ValueError, match="no initialized receipt"):
            transcript.verify(results, deadlines=[], request=SimpleNamespace())
    assert counts["request"] == counts["retention"] == 0


def test_recovery_mode_requires_admitted_model_policy(monkeypatch):
    connection, binding, _ = phase(monkeypatch)
    binding.contract.checks = (SimpleNamespace(kind="model"),)
    monkeypatch.setattr(verification, "task_policy", lambda *_: None)
    monkeypatch.setattr(verification, "replay_model", lambda *_, **__: (None, {}))
    with pytest.raises(ValueError, match="no admitted policy"):
        _ModelVerification(
            connection,
            "deployment",
            binding,
            artifacts=object(),
            derive=lambda *_: None,
            _recovery=True,
        )


@pytest.mark.parametrize("qualified", [False, True])
@pytest.mark.parametrize("sealed", [False, True])
def test_only_qualified_seal_generates_selected_record_keys(monkeypatch, qualified, sealed):
    import agent_storage.postgres.coverage_membership as membership

    connection, binding, counts = phase(monkeypatch)
    source = tuple(SimpleNamespace(record_id=str(index)) for index in range(1000))
    policy = SimpleNamespace(model_profile="fixture", validation_mode="final_certification")
    result = SimpleNamespace(key=SimpleNamespace(record_id="321"))
    selections = []
    probes = []

    def probe(*args):
        probes.append(args)
        return {"sealed": True} if sealed else None

    monkeypatch.setattr(verification, "task_policy", lambda *_, **__: policy)
    monkeypatch.setattr(verification, "read_manifest", lambda *_: source)
    monkeypatch.setattr(
        membership, "membership_records", lambda *args: (source[321],),
    )
    monkeypatch.setattr(verification, "replay_model", lambda *_, **__: (object(), {}))
    monkeypatch.setattr(
        verification, "expected_units", lambda _, rows: selections.append(rows) or (),
    )
    monkeypatch.setattr(membership, "membership_state", probe)
    transcript = _ModelVerification(
        connection, "deployment", binding, artifacts=object(), derive=lambda *_: None,
        _commit_results=(result,), _membership_qualified=qualified,
    )
    assert len(probes) == int(qualified)
    assert selections == ([(source[321],)] if qualified and sealed else [source])
    assert (transcript.membership is not None) == (qualified and sealed)
    assert not counts["page"]  # Does not read accepted history to seal a mutable projection.
