from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.domain.delivery_transaction import (
    DeliveryTransactionRecord,
    DeliveryTransactionState,
    DeliveryTransactionStateError,
    validate_delivery_transaction_transition,
)


def _record(**updates: object) -> DeliveryTransactionRecord:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "transaction_id": uuid4(),
        "deployment_namespace": "cloud-test",
        "action": "deliver",
        "idempotency_key": "key-1",
        "request_hash": "hash-1",
        "state": DeliveryTransactionState.CLAIMED,
        "owner_id": "worker-a",
        "claim_token": "token-a",
        "attempt": 1,
        "created_at": now,
        "updated_at": now,
    }
    values.update(updates)
    return DeliveryTransactionRecord(**values)


def test_transaction_state_machine_allows_only_approved_edges() -> None:
    validate_delivery_transaction_transition(
        DeliveryTransactionState.CLAIMED,
        DeliveryTransactionState.PROCESSING,
    )
    for target in (
        DeliveryTransactionState.COMMITTED,
        DeliveryTransactionState.UNKNOWN,
        DeliveryTransactionState.FAILED,
    ):
        validate_delivery_transaction_transition(DeliveryTransactionState.PROCESSING, target)

    with pytest.raises(DeliveryTransactionStateError):
        validate_delivery_transaction_transition(
            DeliveryTransactionState.UNKNOWN,
            DeliveryTransactionState.COMMITTED,
        )


def test_committed_record_requires_receipt_and_commit_timestamp() -> None:
    with pytest.raises(ValueError, match="receipt_id"):
        _record(state=DeliveryTransactionState.COMMITTED)

    now = datetime.now(UTC)
    committed = _record(
        state=DeliveryTransactionState.COMMITTED,
        receipt_id="key-1",
        created_at=now,
        committed_at=now,
        updated_at=now,
    )
    assert committed.receipt_id == "key-1"
