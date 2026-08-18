from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.delivery_transaction import (
    DeliveryTransactionOwnershipError,
    DeliveryTransactionState,
    DeliveryTransactionStateError,
)
from agent_core.domain.identifiers import new_session_id
from agent_core.ports.delivery_transaction import (
    DeliveryClaimResultType,
    DeliveryReplayResultType,
)
from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_storage import PostgresDeliveryTransactionStore, apply_postgres_migrations


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def namespace(postgres_dsn: str) -> str:
    apply_postgres_migrations(postgres_dsn)
    return f"delivery-txn-{uuid4()}"


def _receipt(
    *, action: str = "deliver", key: str = "key-1", request_hash: str = "hash-1"
) -> IdempotencyRecord:
    return IdempotencyRecord(
        action=action,
        idempotency_key=key,
        request_hash=request_hash,
        status_code=200,
        response_body={"accepted": True},
        created_at=datetime.now(UTC),
    )


def _audit(*, action: str = "deliver", key: str = "key-1") -> DeliveryAuditRecord:
    return DeliveryAuditRecord(
        session_id=new_session_id(),
        action=action,
        status="succeeded",
        status_code=200,
        idempotency_key=key,
        result_metadata={"source": "test"},
        created_at=datetime.now(UTC),
    )


def _store(postgres_dsn: str, namespace: str) -> PostgresDeliveryTransactionStore:
    return PostgresDeliveryTransactionStore(
        postgres_dsn,
        deployment_namespace=namespace,
    )


def test_claim_has_one_owner_and_rejects_hash_reuse(
    postgres_dsn: str,
    namespace: str,
) -> None:
    store = _store(postgres_dsn, namespace)
    first = store.claim(
        namespace=namespace,
        action="deliver",
        key="key-1",
        request_hash="hash-1",
        owner_id="worker-a",
    )
    replay = store.claim(
        namespace=namespace,
        action="deliver",
        key="key-1",
        request_hash="hash-1",
        owner_id="worker-b",
    )
    conflict = store.claim(
        namespace=namespace,
        action="deliver",
        key="key-1",
        request_hash="hash-2",
        owner_id="worker-b",
    )

    assert first.type is DeliveryClaimResultType.CLAIMED
    assert replay.type is DeliveryClaimResultType.IN_PROGRESS
    assert conflict.type is DeliveryClaimResultType.CONFLICT
    assert replay.transaction.transaction_id == first.transaction.transaction_id


def test_concurrent_claims_have_one_owner(postgres_dsn: str, namespace: str) -> None:
    def claim(owner: int):
        return _store(postgres_dsn, namespace).claim(
            namespace=namespace,
            action="deliver",
            key="concurrent-key",
            request_hash="hash-1",
            owner_id=f"worker-{owner}",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(claim, range(8)))

    assert sum(result.type is DeliveryClaimResultType.CLAIMED for result in results) == 1
    assert all(
        result.transaction.transaction_id == results[0].transaction.transaction_id
        for result in results
    )


def test_commit_is_atomic_and_replays_receipt(
    postgres_dsn: str,
    namespace: str,
) -> None:
    store = _store(postgres_dsn, namespace)
    claimed = store.claim(
        namespace=namespace,
        action="deliver",
        key="key-commit",
        request_hash="hash-commit",
        owner_id="worker-a",
    )
    transaction = claimed.transaction
    store.mark_processing(transaction.transaction_id, transaction.claim_token)
    committed = store.commit(
        transaction.transaction_id,
        transaction.claim_token,
        _receipt(key="key-commit", request_hash="hash-commit"),
        _audit(key="key-commit"),
    )
    replay = store.replay(
        namespace=namespace,
        action="deliver",
        key="key-commit",
        request_hash="hash-commit",
    )

    assert committed.transaction.state is DeliveryTransactionState.COMMITTED
    assert replay.type is DeliveryReplayResultType.REPLAY
    assert replay.receipt == committed.receipt
    with psycopg.connect(postgres_dsn) as connection:
        counts = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM control_plane_idempotency_records
                 WHERE deployment_namespace = %s AND action = %s
                   AND idempotency_key = %s),
                (SELECT count(*) FROM control_plane_delivery_audit_records
                 WHERE deployment_namespace = %s AND action = %s
                   AND idempotency_key = %s)
            """,
            (namespace, "deliver", "key-commit", namespace, "deliver", "key-commit"),
        ).fetchone()
    assert counts == (1, 1)


def test_unknown_blocks_replay_and_stale_owner_commit(
    postgres_dsn: str,
    namespace: str,
) -> None:
    store = _store(postgres_dsn, namespace)
    claimed = store.claim(
        namespace=namespace,
        action="deliver",
        key="key-unknown",
        request_hash="hash-unknown",
        owner_id="worker-a",
    )
    transaction = claimed.transaction
    store.mark_processing(transaction.transaction_id, transaction.claim_token)
    store.mark_unknown(transaction.transaction_id, transaction.claim_token)

    replay = store.replay(
        namespace=namespace,
        action="deliver",
        key="key-unknown",
        request_hash="hash-unknown",
    )
    assert replay.type is DeliveryReplayResultType.UNKNOWN
    with pytest.raises(DeliveryTransactionStateError):
        store.commit(
            transaction.transaction_id,
            transaction.claim_token,
            _receipt(key="key-unknown", request_hash="hash-unknown"),
            _audit(key="key-unknown"),
        )

    with pytest.raises(DeliveryTransactionOwnershipError):
        store.mark_failed(transaction.transaction_id, "stale-token")


@pytest.mark.parametrize("failure", ["receipt", "audit"])
def test_commit_failure_rolls_back_receipt_audit_and_state(
    postgres_dsn: str,
    namespace: str,
    failure: str,
) -> None:
    store = _store(postgres_dsn, namespace)
    claimed = store.claim(
        namespace=namespace,
        action="deliver",
        key=f"key-failure-{failure}",
        request_hash="hash-failure",
        owner_id="worker-a",
    )
    transaction = claimed.transaction
    store.mark_processing(transaction.transaction_id, transaction.claim_token)
    receipt = _receipt(key=f"key-failure-{failure}", request_hash="hash-failure")
    audit = _audit(key=f"key-failure-{failure}")
    if failure == "receipt":
        receipt = replace(receipt, status_code=99)
    else:
        audit = audit.model_copy(update={"result_metadata": {"bad": object()}})

    with pytest.raises((psycopg.Error, TypeError, ValueError)):
        store.commit(transaction.transaction_id, transaction.claim_token, receipt, audit)

    state = store.get_state(transaction.transaction_id)
    assert state.state is DeliveryTransactionState.PROCESSING
    with psycopg.connect(postgres_dsn) as connection:
        counts = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM control_plane_idempotency_records
                 WHERE deployment_namespace = %s AND action = %s
                   AND idempotency_key = %s),
                (SELECT count(*) FROM control_plane_delivery_audit_records
                 WHERE deployment_namespace = %s AND action = %s
                   AND idempotency_key = %s)
            """,
            (
                namespace,
                "deliver",
                receipt.idempotency_key,
                namespace,
                "deliver",
                audit.idempotency_key,
            ),
        ).fetchone()
    assert counts == (0, 0)
