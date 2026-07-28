from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.domain.effect_dispatch import (
    EffectDispatchConflictError,
    EffectDispatchStateError,
    EffectDispatchStatus,
    EffectEvidence,
    EffectResolutionOutcome,
    EffectScheduleRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import (
    SessionId,
    new_event_id,
    new_session_id,
    new_tool_call_id,
)
from agent_core.domain.leases import LeaseLostError, WorkerLease
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_storage import (
    PostgresEffectDispatchStore,
    PostgresEventStore,
    PostgresLeaseStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
    rotate_control_plane_epoch,
)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def effect_namespace(postgres_dsn: str) -> Generator[str]:
    namespace = f"effect-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
    yield namespace
    _delete_namespace(postgres_dsn, namespace)


def test_schedule_is_atomic_idempotent_and_preserves_child_execution_scope(
    postgres_dsn: str,
    effect_namespace: str,
) -> None:
    child_session_id = new_session_id()
    root_session_id = new_session_id()
    lease = _acquire(postgres_dsn, effect_namespace, child_session_id)
    request = _request(
        execution_session_id=child_session_id,
        root_session_id=root_session_id,
        sequence=0,
    )
    stores = (
        _store(postgres_dsn, effect_namespace),
        _store(postgres_dsn, effect_namespace),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        dispatched = tuple(
            executor.map(lambda store: store.schedule(request, fence=lease.fence), stores)
        )

    assert dispatched[0] == dispatched[1]
    assert dispatched[0].execution_session_id == child_session_id
    assert dispatched[0].root_session_id == root_session_id
    assert dispatched[0].status is EffectDispatchStatus.PENDING
    assert PostgresEventStore(
        postgres_dsn,
        deployment_namespace=effect_namespace,
    ).list_for_session(child_session_id) == [request.started_event]
    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT execution_session_id, root_session_id, count(*) OVER ()
            FROM effect_outbox
            WHERE deployment_namespace = %s
            """,
            (effect_namespace,),
        ).fetchone()
    assert row == (child_session_id, root_session_id, 1)


def test_schedule_rolls_back_outbox_when_event_version_fails(
    postgres_dsn: str,
    effect_namespace: str,
) -> None:
    session_id = new_session_id()
    lease = _acquire(postgres_dsn, effect_namespace, session_id)
    request = _request(
        execution_session_id=session_id,
        root_session_id=session_id,
        sequence=1,
    )

    with pytest.raises(ValueError, match="duplicate or conflicting session event"):
        _store(postgres_dsn, effect_namespace).schedule(request, fence=lease.fence)

    assert _row_count(postgres_dsn, effect_namespace, "effect_outbox") == 0
    assert (
        PostgresEventStore(
            postgres_dsn,
            deployment_namespace=effect_namespace,
        ).list_for_session(session_id)
        == []
    )


def test_schedule_rejects_same_ledger_key_with_different_request_hash(
    postgres_dsn: str,
    effect_namespace: str,
) -> None:
    session_id = new_session_id()
    lease = _acquire(postgres_dsn, effect_namespace, session_id)
    request = _request(
        execution_session_id=session_id,
        root_session_id=session_id,
        sequence=0,
    )
    store = _store(postgres_dsn, effect_namespace)
    store.schedule(request, fence=lease.fence)
    conflict = request.model_copy(update={"request_hash": "b" * 64})

    with pytest.raises(EffectDispatchConflictError):
        store.schedule(conflict, fence=lease.fence)

    assert _row_count(postgres_dsn, effect_namespace, "effect_outbox") == 1


def test_schedule_rejects_stale_fence_even_for_idempotent_retry(
    postgres_dsn: str,
    effect_namespace: str,
) -> None:
    session_id = new_session_id()
    lease = _acquire(postgres_dsn, effect_namespace, session_id)
    request = _request(
        execution_session_id=session_id,
        root_session_id=session_id,
        sequence=0,
    )
    store = _store(postgres_dsn, effect_namespace)
    store.schedule(request, fence=lease.fence)
    _leases(postgres_dsn, effect_namespace).release(session_id, fence=lease.fence)

    with pytest.raises(LeaseLostError):
        store.schedule(request, fence=lease.fence)


def test_effect_dispatch_isolated_by_deployment_namespace(postgres_dsn: str) -> None:
    session_id = new_session_id()
    root_session_id = new_session_id()
    first_namespace = f"effect-a-{uuid4()}"
    second_namespace = f"effect-b-{uuid4()}"
    for namespace in (first_namespace, second_namespace):
        bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
    try:
        first_lease = _acquire(postgres_dsn, first_namespace, session_id)
        second_lease = _acquire(postgres_dsn, second_namespace, session_id)
        request = _request(
            execution_session_id=session_id,
            root_session_id=root_session_id,
            sequence=0,
        )

        first = _store(postgres_dsn, first_namespace).schedule(request, fence=first_lease.fence)
        second = _store(postgres_dsn, second_namespace).schedule(request, fence=second_lease.fence)

        assert first.dispatch_id != second.dispatch_id
        assert _row_count(postgres_dsn, first_namespace, "effect_outbox") == 1
        assert _row_count(postgres_dsn, second_namespace, "effect_outbox") == 1
    finally:
        _delete_namespace(postgres_dsn, first_namespace)
        _delete_namespace(postgres_dsn, second_namespace)


def test_skip_locked_claim_allows_only_one_consumer_and_terminal_is_fenced(
    postgres_dsn: str,
    effect_namespace: str,
) -> None:
    session_id = new_session_id()
    lease = _acquire(postgres_dsn, effect_namespace, session_id)
    store = _store(postgres_dsn, effect_namespace)
    dispatch = store.schedule(
        _request(
            execution_session_id=session_id,
            root_session_id=session_id,
            sequence=0,
        ),
        fence=lease.fence,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = tuple(
            executor.map(
                lambda candidate: candidate.claim_next(
                    session_id,
                    fence=lease.fence,
                    claim_ttl=timedelta(seconds=30),
                ),
                (_store(postgres_dsn, effect_namespace),) * 2,
            )
        )

    assert sum(claim is not None for claim in claims) == 1
    claim = next(claim for claim in claims if claim is not None)
    assert claim.dispatch.dispatch_id == dispatch.dispatch_id
    assert claim.dispatch.status is EffectDispatchStatus.CLAIMED

    _leases(postgres_dsn, effect_namespace).release(session_id, fence=lease.fence)
    with pytest.raises(LeaseLostError):
        store.complete(
            claim,
            result=_result(),
            terminal_event=_event(session_id, 1, EventType.TOOL_EXECUTION_COMPLETED),
        )
    events = PostgresEventStore(
        postgres_dsn,
        deployment_namespace=effect_namespace,
    ).list_for_session(session_id)
    assert [event.event_id for event in events] == [dispatch.intent_event_id]


def test_terminal_success_commits_result_event_and_dispatch_together(
    postgres_dsn: str,
    effect_namespace: str,
) -> None:
    session_id = new_session_id()
    lease = _acquire(postgres_dsn, effect_namespace, session_id)
    store = _store(postgres_dsn, effect_namespace)
    request = _request(
        execution_session_id=session_id,
        root_session_id=session_id,
        sequence=0,
    )
    store.schedule(request, fence=lease.fence)
    claim = store.claim_next(
        session_id,
        fence=lease.fence,
        claim_ttl=timedelta(seconds=30),
    )
    assert claim is not None
    terminal = _event(session_id, 1, EventType.TOOL_EXECUTION_COMPLETED)

    result = _result()
    stored_event = store.complete(claim, result=result, terminal_event=terminal)

    assert stored_event == terminal
    events = PostgresEventStore(
        postgres_dsn,
        deployment_namespace=effect_namespace,
    ).list_for_session(session_id)
    assert events == [request.started_event, terminal]
    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT status, terminal_event_id, result IS NOT NULL
            FROM effect_outbox
            WHERE deployment_namespace = %s
            """,
            (effect_namespace,),
        ).fetchone()
    assert row == ("succeeded", terminal.event_id, True)

    response_loss_retry = store.schedule(request, fence=lease.fence)
    assert response_loss_retry.status is EffectDispatchStatus.SUCCEEDED
    assert response_loss_retry.result == result


def test_terminal_event_failure_rolls_back_dispatch_transition(
    postgres_dsn: str,
    effect_namespace: str,
) -> None:
    session_id = new_session_id()
    lease = _acquire(postgres_dsn, effect_namespace, session_id)
    store = _store(postgres_dsn, effect_namespace)
    store.schedule(
        _request(
            execution_session_id=session_id,
            root_session_id=session_id,
            sequence=0,
        ),
        fence=lease.fence,
    )
    claim = store.claim_next(session_id, fence=lease.fence, claim_ttl=timedelta(seconds=30))
    assert claim is not None

    with pytest.raises(ValueError, match="duplicate or conflicting session event"):
        store.complete(
            claim,
            result=_result(),
            terminal_event=_event(session_id, 9, EventType.TOOL_EXECUTION_COMPLETED),
        )

    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT status, terminal_event_id FROM effect_outbox
            WHERE deployment_namespace = %s AND dispatch_id = %s
            """,
            (effect_namespace, claim.dispatch.dispatch_id),
        ).fetchone()
    assert row == ("claimed", None)


def test_epoch_rotation_exposes_old_claim_for_reconciliation(
    postgres_dsn: str,
    effect_namespace: str,
) -> None:
    session_id = new_session_id()
    first = _acquire(postgres_dsn, effect_namespace, session_id)
    store = _store(postgres_dsn, effect_namespace)
    store.schedule(
        _request(
            execution_session_id=session_id,
            root_session_id=session_id,
            sequence=0,
        ),
        fence=first.fence,
    )
    old_claim = store.claim_next(session_id, fence=first.fence, claim_ttl=timedelta(minutes=5))
    assert old_claim is not None
    rotate_control_plane_epoch(postgres_dsn, deployment_namespace=effect_namespace)
    second = _acquire(
        postgres_dsn,
        effect_namespace,
        session_id,
        owner="worker-b",
    )

    assert store.list_reconcilable(
        session_id,
        current_fence=second.fence,
    ) == (old_claim,)
    assert (
        store.reconcile_expired(
            old_claim.dispatch.dispatch_id,
            old_claim=old_claim,
            current_fence=second.fence,
            evidence=_evidence("epoch_replaced"),
        ).status
        is EffectDispatchStatus.UNCERTAIN
    )


def test_concurrent_reconciliation_allows_one_claim_cas(
    postgres_dsn: str,
    effect_namespace: str,
) -> None:
    session_id = new_session_id()
    first = _acquire(postgres_dsn, effect_namespace, session_id)
    store = _store(postgres_dsn, effect_namespace)
    store.schedule(
        _request(execution_session_id=session_id, root_session_id=session_id, sequence=0),
        fence=first.fence,
    )
    old_claim = store.claim_next(session_id, fence=first.fence, claim_ttl=timedelta(seconds=30))
    assert old_claim is not None
    _expire_claim_and_lease(postgres_dsn, effect_namespace, old_claim.dispatch.dispatch_id)
    second = _acquire(postgres_dsn, effect_namespace, session_id, owner="worker-b")
    recovery_claims = store.list_reconcilable(
        session_id,
        current_fence=second.fence,
    )
    assert len(recovery_claims) == 1
    recovery_claim = recovery_claims[0]
    assert recovery_claim.dispatch.dispatch_id == old_claim.dispatch.dispatch_id

    def reconcile(candidate: PostgresEffectDispatchStore) -> object:
        try:
            return candidate.reconcile_expired(
                recovery_claim.dispatch.dispatch_id,
                old_claim=recovery_claim,
                current_fence=second.fence,
                evidence=_evidence("claim_expired"),
            )
        except EffectDispatchStateError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(reconcile, (_store(postgres_dsn, effect_namespace),) * 2))
    assert (
        sum(getattr(result, "status", None) is EffectDispatchStatus.UNCERTAIN for result in results)
        == 1
    )
    assert sum(isinstance(result, EffectDispatchStateError) for result in results) == 1


def test_expired_claim_requires_reconciliation_and_never_returns_to_pending(
    postgres_dsn: str,
    effect_namespace: str,
) -> None:
    session_id = new_session_id()
    first = _acquire(postgres_dsn, effect_namespace, session_id)
    store = _store(postgres_dsn, effect_namespace)
    store.schedule(
        _request(
            execution_session_id=session_id,
            root_session_id=session_id,
            sequence=0,
        ),
        fence=first.fence,
    )
    old_claim = store.claim_next(
        session_id,
        fence=first.fence,
        claim_ttl=timedelta(seconds=30),
    )
    assert old_claim is not None
    _expire_claim_and_lease(postgres_dsn, effect_namespace, old_claim.dispatch.dispatch_id)
    second = _acquire(
        postgres_dsn,
        effect_namespace,
        session_id,
        owner="worker-b",
    )
    recovery_store = _store(postgres_dsn, effect_namespace)
    discovered = recovery_store.list_reconcilable(
        session_id,
        current_fence=second.fence,
    )
    assert len(discovered) == 1
    recovery_claim = discovered[0]
    assert recovery_claim.dispatch.dispatch_id == old_claim.dispatch.dispatch_id
    assert recovery_claim.claim_fence == old_claim.claim_fence

    reconciled = recovery_store.reconcile_expired(
        recovery_claim.dispatch.dispatch_id,
        old_claim=recovery_claim,
        current_fence=second.fence,
        evidence=_evidence("claim_expired"),
    )

    assert reconciled.status is EffectDispatchStatus.UNCERTAIN
    assert reconciled.terminal_event_id is None
    assert (
        recovery_store.claim_next(
            session_id,
            fence=second.fence,
            claim_ttl=timedelta(seconds=30),
        )
        is None
    )
    terminal = _event(session_id, 1, EventType.TOOL_EXECUTION_FAILED)
    assert (
        recovery_store.resolve_uncertain(
            reconciled.dispatch_id,
            current_fence=second.fence,
            evidence=_evidence("provider_proved_no_effect"),
            outcome=EffectResolutionOutcome.FAILED_NO_EFFECT,
            terminal_event=terminal,
        )
        == terminal
    )
    with psycopg.connect(postgres_dsn) as connection:
        evidence_row = connection.execute(
            """
            SELECT evidence_history FROM effect_outbox
            WHERE deployment_namespace = %s AND dispatch_id = %s
            """,
            (effect_namespace, reconciled.dispatch_id),
        ).fetchone()
    assert evidence_row is not None
    evidence_history = evidence_row[0]
    assert [item["reason_code"] for item in evidence_history] == [
        "claim_expired",
        "provider_proved_no_effect",
    ]


def test_failed_no_effect_retry_is_monotonic_and_idempotent(
    postgres_dsn: str,
    effect_namespace: str,
) -> None:
    session_id = new_session_id()
    lease = _acquire(postgres_dsn, effect_namespace, session_id)
    store = _store(postgres_dsn, effect_namespace)
    first = store.schedule(
        _request(
            execution_session_id=session_id,
            root_session_id=session_id,
            sequence=0,
        ),
        fence=lease.fence,
    )
    claim = store.claim_next(
        session_id,
        fence=lease.fence,
        claim_ttl=timedelta(seconds=30),
    )
    assert claim is not None
    store.fail_no_effect(
        claim,
        evidence=_evidence("provider_rejected_before_execution"),
        terminal_event=_event(session_id, 1, EventType.TOOL_EXECUTION_FAILED),
    )
    retry_event = _event(session_id, 2, EventType.TOOL_EXECUTION_STARTED)

    retry = store.retry_failed_no_effect(
        first.dispatch_id,
        current_fence=lease.fence,
        retry_key="operator-retry-1",
        started_event=retry_event,
    )
    semantic_retry = retry_event.model_copy(
        update={"event_id": new_event_id(), "sequence": 999, "created_at": datetime.now(UTC)}
    )
    duplicate = store.retry_failed_no_effect(
        first.dispatch_id,
        current_fence=lease.fence,
        retry_key="operator-retry-1",
        started_event=semantic_retry,
    )

    assert retry == duplicate
    assert retry.attempt == 2
    assert retry.status is EffectDispatchStatus.PENDING
    assert _row_count(postgres_dsn, effect_namespace, "effect_outbox") == 2

    conflicting_event = _event(session_id, 2, EventType.TOOL_EXECUTION_STARTED)
    with pytest.raises(EffectDispatchConflictError, match="retry key"):
        store.retry_failed_no_effect(
            first.dispatch_id,
            current_fence=lease.fence,
            retry_key="operator-retry-1",
            started_event=conflicting_event,
        )
    with pytest.raises(EffectDispatchStateError, match="latest"):
        store.retry_failed_no_effect(
            first.dispatch_id,
            current_fence=lease.fence,
            retry_key="operator-retry-2",
            started_event=conflicting_event,
        )


def _store(dsn: str, namespace: str) -> PostgresEffectDispatchStore:
    return PostgresEffectDispatchStore(dsn, deployment_namespace=namespace)


def _leases(dsn: str, namespace: str) -> PostgresLeaseStore:
    return PostgresLeaseStore(dsn, deployment_namespace=namespace)


def _acquire(
    dsn: str,
    namespace: str,
    session_id: SessionId,
    *,
    owner: str = "worker-a",
) -> WorkerLease:
    return _leases(dsn, namespace).acquire(
        session_id,
        owner_instance_id=owner,
        ttl=timedelta(seconds=30),
    )


def _request(
    *,
    execution_session_id: SessionId,
    root_session_id: SessionId,
    sequence: int,
) -> EffectScheduleRequest:
    return EffectScheduleRequest(
        root_session_id=root_session_id,
        identity=EffectIdentity(
            authority_scope_hash="authority",
            tool_name="publish",
            operation_kind="create",
            target_hash="target",
            canonical_effect_hash="effect",
            external_operation_id_hash="provider-operation",
        ),
        request_hash="a" * 64,
        payload_artifact_ref="artifact://effect/request.json",
        started_event=_event(
            execution_session_id,
            sequence,
            EventType.TOOL_EXECUTION_STARTED,
        ),
    )


def _event(session_id: SessionId, sequence: int, event_type: EventType) -> SessionEvent:
    return SessionEvent(
        event_id=new_event_id(),
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        payload={},
        actor=EventActor.TOOL,
        created_at=datetime.now(UTC),
        idempotency_key=f"{event_type.value}-{sequence}-{uuid4()}",
    )


def _result() -> ToolResult:
    return ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output="created",
        metadata={"provider_operation_id_hash": "provider-operation"},
    )


def _evidence(reason: str) -> EffectEvidence:
    return EffectEvidence(reason_code=reason, provider_operation_id_hash="c" * 64)


def _row_count(dsn: str, namespace: str, table: str) -> int:
    assert table == "effect_outbox"
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            "SELECT count(*) FROM effect_outbox WHERE deployment_namespace = %s",
            (namespace,),
        ).fetchone()
    assert row is not None
    return int(row[0])


def _expire_claim_and_lease(dsn: str, namespace: str, dispatch_id: UUID) -> None:
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            UPDATE effect_outbox
            SET updated_at = created_at,
                claim_expires_at = created_at + interval '1 microsecond'
            WHERE deployment_namespace = %s AND dispatch_id = %s
            """,
            (namespace, dispatch_id),
        )
        connection.execute(
            """
            UPDATE worker_leases
            SET acquired_at = transaction_timestamp() - interval '3 seconds',
                heartbeat_at = transaction_timestamp() - interval '2 seconds',
                expires_at = transaction_timestamp() - interval '1 second'
            WHERE deployment_namespace = %s
            """,
            (namespace,),
        )


def _delete_namespace(dsn: str, namespace: str) -> None:
    with psycopg.connect(dsn) as connection:
        for table in (
            "effect_outbox",
            "session_events",
            "session_streams",
            "worker_leases",
            "control_plane_epochs",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE deployment_namespace = %s",
                (namespace,),
            )
