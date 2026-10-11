"""Real PostgreSQL exact claim refuses without changing sibling or rejected rows."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.effect_dispatch import (
    EffectDispatchStatus,
    EffectEvidence,
    EffectScheduleRequest,
)
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.tools import (
    ToolCallStatus,
    ToolExecutionLocation,
    ToolReceipt,
    ToolRisk,
)
from agent_core.ports import WorkerMutationAuthority
from agent_storage import PostgresLeaseStore, bootstrap_control_plane_epoch
from agent_storage.postgres.outbox import PostgresEffectDispatchStore
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from tests.agent_storage import test_postgres_effect_payload_transactions as payload_tests
from tests.agent_storage.test_postgres_effect_dispatch import _event, _request, _result
from tests.agent_tools.test_effect_exact import setup_gateway
from tests.agent_tools.test_effect_guard import _call

dsn = payload_tests.dsn
postgres_dsn = payload_tests.postgres_dsn


def prepared(dsn, namespace=None, session=None):
    if namespace is None:
        namespace = "exact-" + uuid4().hex
        bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    session = session or new_session_id()
    leases = PostgresLeaseStore(dsn, deployment_namespace=namespace)
    lease = leases.acquire(session, owner_instance_id="worker-a", ttl=timedelta(minutes=2))
    store = PostgresEffectDispatchStore(dsn, deployment_namespace=namespace)
    request = _request(execution_session_id=session, root_session_id=session, sequence=0)
    return store, leases, lease, store.schedule(request, fence=lease.fence)


def rows(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        return {
            "outbox": connection.execute(
                "SELECT * FROM effect_outbox ORDER BY dispatch_id"
            ).fetchall(),
            "events": connection.execute(
                "SELECT * FROM session_events ORDER BY session_id, sequence"
            ).fetchall(),
        }


def claim(store, lease, expected):
    return store.claim_exact(
        lease.session_id, expected=expected, fence=lease.fence,
        claim_ttl=timedelta(seconds=30),
    )


def test_exact_mixed_queue_changes_only_scheduled_row(dsn):
    store, leases, lease, sibling = prepared(dsn)
    request = _request(
        execution_session_id=lease.session_id, root_session_id=lease.session_id, sequence=1
    )
    request = request.model_copy(update={
        "identity": request.identity.model_copy(update={"target_hash": "second"})
    })
    expected = store.schedule(request, fence=lease.fence)
    before = rows(dsn)
    result = claim(store, lease, expected)
    assert result is not None and result.dispatch.dispatch_id == expected.dispatch_id
    after = rows(dsn)
    assert next(
        row for row in before["outbox"] if row["dispatch_id"] == sibling.dispatch_id
    ) == next(
        row for row in after["outbox"] if row["dispatch_id"] == sibling.dispatch_id
    )
    assert before["events"] == after["events"]
    assert result.claim_fence == lease.fence
    assert claim(store, lease, expected) is None
    assert rows(dsn) == after


@pytest.mark.parametrize("fault", [
    "missing", "session", "root", "identity", "hash", "artifact", "event", "attempt",
    "timestamp", "status", "extra", "identity_extra", "invalid_hash",
])
def test_wrong_or_unsupported_expected_changes_no_rows(dsn, fault):
    store, leases, lease, expected = prepared(dsn)
    changes = {
        "missing": {"dispatch_id": uuid4()},
        "session": {"execution_session_id": new_session_id()},
        "root": {"root_session_id": new_session_id()},
        "identity": {"identity": expected.identity.model_copy(update={"target_hash": "other"})},
        "hash": {"request_hash": "b" * 64},
        "artifact": {"payload_artifact_ref": "artifact://wrong"},
        "event": {"intent_event_id": uuid4()},
        "attempt": {"attempt": 2},
        "timestamp": {"created_at": expected.created_at - timedelta(seconds=1)},
        "status": {"status": EffectDispatchStatus.CLAIMED},
        "extra": {"injected": True},
        "identity_extra": {"identity": expected.identity.model_copy(update={"injected": True})},
        "invalid_hash": {"request_hash": "invalid"},
    }
    before = rows(dsn)
    candidate = expected.model_copy(update=changes[fault])
    if fault in {"extra", "identity_extra", "invalid_hash"}:
        with pytest.raises(ValueError):
            claim(store, lease, candidate)
    else:
        assert claim(store, lease, candidate) is None
    assert rows(dsn) == before


def test_foreign_deployment_and_session_never_claim(dsn):
    store, leases, lease, expected = prepared(dsn)
    other, _, other_lease, foreign = prepared(dsn, session=lease.session_id)
    before = rows(dsn)
    assert claim(other, other_lease, expected) is None
    assert claim(store, lease, foreign) is None
    assert rows(dsn) == before
    same_deployment, _, foreign_lease, foreign_session = prepared(
        dsn, namespace=store._namespace
    )
    before = rows(dsn)
    assert claim(store, lease, foreign_session) is None
    assert claim(same_deployment, foreign_lease, expected) is None
    assert rows(dsn) == before


def test_two_exact_claimers_only_one_wins_without_draining(dsn):
    store, leases, lease, expected = prepared(dsn)
    barrier = Barrier(2)

    def compete(_):
        barrier.wait(timeout=5)
        fresh = PostgresEffectDispatchStore(dsn, deployment_namespace=store._namespace)
        return claim(fresh, lease, expected)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(compete, range(2)))
    assert sum(result is not None for result in results) == 1
    before = rows(dsn)
    assert claim(store, lease, expected) is None
    assert rows(dsn) == before


def test_locked_candidate_does_not_fall_back_to_sibling(dsn):
    store, leases, lease, expected = prepared(dsn)
    request = _request(
        execution_session_id=lease.session_id, root_session_id=lease.session_id, sequence=1
    )
    store.schedule(request.model_copy(update={
        "identity": request.identity.model_copy(update={"target_hash": "sibling"})
    }), fence=lease.fence)
    before = rows(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("SELECT 1 FROM effect_outbox WHERE dispatch_id=%s FOR UPDATE",
                           (expected.dispatch_id,))
        assert claim(store, lease, expected) is None
    assert rows(dsn) == before
    assert claim(store, lease, expected) is not None


def test_replacement_worker_fence_refuses_old_owner_without_writes(dsn):
    store, leases, first, expected = prepared(dsn)
    leases.release(first.session_id, fence=first.fence)
    second = leases.acquire(first.session_id, owner_instance_id="worker-b",
                            ttl=timedelta(minutes=2))
    before = rows(dsn)
    with pytest.raises(LeaseLostError):
        claim(store, first, expected)
    assert rows(dsn) == before
    barrier = Barrier(2)

    def compete(owner):
        barrier.wait(timeout=5)
        try:
            return claim(store, owner, expected)
        except LeaseLostError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        old, result = list(executor.map(compete, (first, second)))
    assert old == "stale"
    assert result is not None and result.claim_fence == second.fence


def test_changed_durable_request_refuses_without_claim(dsn):
    from psycopg.types.json import Jsonb

    store, leases, lease, expected = prepared(dsn)
    changed = expected.identity.model_copy(update={"target_hash": "changed-after-schedule"})
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE effect_outbox SET effect_identity=%s, ledger_key=%s WHERE dispatch_id=%s",
            (Jsonb(changed.model_dump(mode="json")), changed.ledger_key(), expected.dispatch_id),
        )
    before = rows(dsn)
    assert claim(store, lease, expected) is None
    assert rows(dsn) == before


@pytest.mark.parametrize("seconds", [0, -1])
def test_invalid_claim_ttl_changes_no_rows(dsn, seconds):
    store, leases, lease, expected = prepared(dsn)
    before = rows(dsn)
    with pytest.raises(ValueError, match="positive"):
        store.claim_exact(lease.session_id, expected=expected, fence=lease.fence,
                          claim_ttl=timedelta(seconds=seconds))
    assert rows(dsn) == before


@pytest.mark.parametrize("target", ["dispatch", "identity", "fence"])
def test_injected_typed_extras_cannot_bypass_exact_claim(dsn, target):
    store, leases, lease, expected = prepared(dsn)
    value = {"dispatch": expected, "identity": expected.identity, "fence": lease.fence}[target]
    object.__setattr__(value, "__pydantic_extra__", {"unsupported": True})
    before = rows(dsn)
    with pytest.raises(ValueError, match="unsupported"):
        claim(store, lease, expected)
    assert rows(dsn) == before


@pytest.mark.parametrize("value", [True, 1.0])
@pytest.mark.parametrize("target", ["attempt", "fence"])
def test_coercible_typed_numbers_refused_without_any_queue_write(dsn, value, target):
    store, leases, lease, expected = prepared(dsn)
    request = _request(
        execution_session_id=lease.session_id, root_session_id=lease.session_id, sequence=1
    )
    store.schedule(request.model_copy(update={
        "identity": request.identity.model_copy(update={"target_hash": "sibling"})
    }), fence=lease.fence)
    fence = lease.fence
    if target == "attempt":
        expected = expected.model_copy(update={"attempt": value})
    else:
        fence = fence.model_copy(update={"fencing_token": value})
    before = rows(dsn)
    with pytest.raises(ValueError):
        store.claim_exact(lease.session_id, expected=expected, fence=fence,
                          claim_ttl=timedelta(seconds=30))
    assert rows(dsn) == before


@pytest.mark.parametrize("status", ["claimed", "uncertain", "failed_no_effect", "succeeded"])
def test_nonpending_durable_candidate_changes_no_rows(dsn, status):
    store, leases, lease, expected = prepared(dsn)
    claimed = claim(store, lease, expected)
    assert claimed is not None
    terminal = _event(lease.session_id, 1, EventType.TOOL_EXECUTION_FAILED)
    evidence = EffectEvidence(reason_code="test_outcome")
    if status == "succeeded":
        store.complete(claimed, result=_result(), terminal_event=_event(
            lease.session_id, 1, EventType.TOOL_EXECUTION_COMPLETED
        ))
    elif status == "uncertain":
        store.mark_uncertain(claimed, evidence=evidence, terminal_event=terminal)
    elif status == "failed_no_effect":
        store.fail_no_effect(claimed, evidence=evidence, terminal_event=terminal)
    before = rows(dsn)
    assert claim(store, lease, expected) is None
    assert rows(dsn) == before


@pytest.mark.parametrize("fault", [
    "result_extra", "receipt_extra", "receipt_bool", "receipt_float",
    "numeric_output", "failed_status", "valid_legacy_replay",
])
def test_raw_postgres_result_replay_refuses_corruption_without_queue_write(dsn, fault):
    from agent_tools.effect_guard_support import effect_identity

    store, leases, lease, sibling = prepared(dsn)
    guarded, fake_dispatch, gateway, payloads = setup_gateway()
    call = _call("dataset.snapshot.create")
    identity = effect_identity(call, guarded._authority_scope)
    expected = store.schedule(EffectScheduleRequest(
        root_session_id=lease.session_id, identity=identity,
        request_hash=identity.canonical_effect_hash,
        payload_artifact_ref=f"artifact://{uuid4()}",
        started_event=_event(lease.session_id, 1, EventType.TOOL_EXECUTION_STARTED),
    ), fence=lease.fence)
    claimed = claim(store, lease, expected)
    assert claimed is not None
    result = _result().model_copy(update={
        "tool_call_id": call.tool_call_id,
        "receipt": ToolReceipt(
            tool_name=call.name, execution_location=ToolExecutionLocation.HOST,
            scopes=("history.snapshot.write",), risk=ToolRisk.WRITE,
            status="executed", output_bytes=1, idempotency_key="opaque-key",
        ),
    })
    store.complete(claimed, result=result, terminal_event=_event(
        lease.session_id, 2, EventType.TOOL_EXECUTION_COMPLETED
    ))
    raw = result.model_dump(mode="json")
    if fault == "result_extra":
        raw["unsupported"] = True
    elif fault == "receipt_extra":
        raw["receipt"]["unsupported"] = True
    elif fault in {"receipt_bool", "receipt_float"}:
        raw["receipt"]["output_bytes"] = True if fault == "receipt_bool" else 1.0
    elif fault == "numeric_output":
        raw["output"] = 123
    elif fault == "failed_status":
        raw["status"] = ToolCallStatus.FAILED.value
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE effect_outbox SET result=%s WHERE dispatch_id=%s",
                           (Jsonb(raw), expected.dispatch_id))
    guarded._dispatch = store
    guarded._execution_session_id = guarded._root_session_id = lease.session_id
    guarded._fence = lease.fence
    payloads.call = call
    guarded._mutation_authority = lambda: WorkerMutationAuthority(
        deployment_namespace=store._namespace, session_id=lease.session_id,
        lease_fence=lease.fence, expected_stream_revision=2,
    )

    def current_ownership():
        current = leases.get(lease.session_id)
        assert current is not None and current.fence == lease.fence

    guarded._ownership_check = current_ownership
    before = rows(dsn)
    if fault == "valid_legacy_replay":
        assert guarded.execute_exact(call) == result
        # A newly constructed gateway reuses the same persisted output too.
        fresh = type(guarded)(
            gateway, dispatch=store, artifacts=None,
            execution_session_id=lease.session_id, root_session_id=lease.session_id,
            fence=lease.fence, claim_ttl=guarded._claim_ttl,
            authority_scope=guarded._authority_scope, next_event=guarded._next_event,
            accept_event=guarded._accept_event, ownership_check=current_ownership,
            effect_payloads=payloads, mutation_authority=guarded._mutation_authority,
        )
        assert fresh.execute_exact(call) == result
    else:
        with pytest.raises(ValueError):
            guarded.execute_exact(call)
    assert gateway.calls == fake_dispatch.claims == 0
    assert rows(dsn) == before
    assert next(row for row in before["outbox"] if row["dispatch_id"] == sibling.dispatch_id)[
        "status"
    ] == "pending"
