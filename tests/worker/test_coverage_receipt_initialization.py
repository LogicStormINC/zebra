"""Native receipt initialization probes after committed acceptance, before cert."""
# ruff: noqa: F811

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage.postgres import coverage as storage
from agent_storage.postgres import coverage_model_budget as budget
from agent_storage.postgres.coverage_execution_receipt_read import read_execution_receipt
from agent_storage.postgres.events import append_event_in_transaction
from zebra_agent_worker.coverage_continuation import NATIVE_CONTINUATION_VERIFIER

from tests.worker.test_coverage_execution_receipts import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_cloud,
    native_worker,
    postgres_dsn,
    receipt_composition,
    receipt_protocol,
    run,
)


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("qualified", [False, True])
@pytest.mark.parametrize("damage", [False, True])
def test_native_receipt_initialization_keeps_source_proof_and_legacy_replay(
    native_worker, monkeypatch, qualified, damage,
):
    env = native_worker
    initialize = storage.PostgresCoverageStore.__init__
    stores = []

    def configured(store, *args, **kwargs):
        if qualified:
            kwargs["execution_receipt_verifier"] = NATIVE_CONTINUATION_VERIFIER
        initialize(store, *args, **kwargs)
        stores.append(store)

    monkeypatch.setattr(storage.PostgresCoverageStore, "__init__", configured)
    original_mint, original_replay = storage.mint_execution_receipt, budget.replay_model
    replays = 0

    def replay(*args, **kwargs):
        nonlocal replays
        replays += 1
        return original_replay(*args, **kwargs)

    monkeypatch.setattr(budget, "replay_model", replay)

    class ProbeFinished(BaseException):
        pass

    def probe(connection, deployment, binding, event, verified, **kwargs):
        original_mint(connection, deployment, binding, event, verified, **kwargs)
        store = stores[-1]
        facts = read_execution_receipt(connection, NAMESPACE, binding)
        assert facts is not None
        if damage:
            connection.execute("UPDATE coverage_model_ledger SET charged_tokens=charged_tokens+1")
        before, old_replays = list(env.client.calls), replays
        # Probe the shared reuse helper in the actual mint transaction. Pure tests
        # cover initialize's fallback; native full execution is covered by workload.
        if damage and qualified:
            with pytest.raises(ValueError, match="native model source|counters"):
                store._receipt_model_policy(connection, binding, fence=probe_fence[0])
        else:
            policy = store._receipt_model_policy(connection, binding, fence=probe_fence[0])
            assert policy == (facts.budget.policy if qualified else None)
            if qualified:
                assert env.client.calls == before
                source = connection.execute(
                    "SELECT * FROM session_events WHERE event_type=%s ORDER BY sequence LIMIT 1",
                    (EventType.COVERAGE_MODEL_CALL_RESERVED.value,),
                ).fetchone()
                append_event_in_transaction(connection, deployment, SessionEvent.create(
                    session_id=env.session, sequence=event.sequence + 1,
                    event_type=EventType.COVERAGE_MODEL_CALL_RESERVED,
                    actor=EventActor.SYSTEM, payload=source["payload"],
                ))
                assert read_execution_receipt(
                    connection, NAMESPACE, binding, _unchanged_model=True,
                ) is None
                with pytest.raises(ValueError, match="native model source"):
                    read_execution_receipt(connection, NAMESPACE, binding)
        assert replays == old_replays
        raise ProbeFinished

    probe_fence = []
    original_commit = storage.PostgresCoverageStore.commit

    def commit(store, request, *, fence):
        probe_fence[:] = [fence]
        return original_commit(store, request, fence=fence)

    monkeypatch.setattr(storage.PostgresCoverageStore, "commit", commit)
    monkeypatch.setattr(storage, "mint_execution_receipt", probe)
    with pytest.raises(ProbeFinished):
        run(env)
