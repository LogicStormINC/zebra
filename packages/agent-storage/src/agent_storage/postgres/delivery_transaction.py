"""PostgreSQL delivery transaction coordinator for the cloud profile."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.delivery_transaction import (
    DeliveryTransactionConflictError,
    DeliveryTransactionInvariantError,
    DeliveryTransactionNotFoundError,
    DeliveryTransactionOwnershipError,
    DeliveryTransactionRecord,
    DeliveryTransactionState,
    DeliveryTransactionStateError,
    validate_delivery_transaction_transition,
)
from agent_core.ports.delivery_transaction import (
    DeliveryClaimResult,
    DeliveryClaimResultType,
    DeliveryCommitResult,
    DeliveryReplayResult,
    DeliveryReplayResultType,
    DeliveryTransactionPort,
)
from agent_core.ports.idempotency_store import IdempotencyRecord
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase


class PostgresDeliveryTransactionStore(DeliveryTransactionPort):
    """Own delivery lifecycle rows and commit receipt/audit in one connection."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def claim(
        self,
        *,
        namespace: str,
        action: str,
        key: str,
        request_hash: str,
        owner_id: str,
    ) -> DeliveryClaimResult:
        self._require_namespace(namespace)
        action = _required_text(action, "action")
        key = _required_text(key, "key")
        request_hash = _required_text(request_hash, "request_hash")
        owner_id = _required_text(owner_id, "owner_id")
        transaction_id = uuid4()
        claim_token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        with self._database.connect() as connection:
            inserted = connection.execute(
                """
                INSERT INTO delivery_transactions (
                    deployment_namespace, id, action, idempotency_key, request_hash,
                    state, owner_id, claim_token, attempt, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (deployment_namespace, action, idempotency_key) DO NOTHING
                RETURNING deployment_namespace, id, action, idempotency_key,
                          request_hash, state, owner_id, claim_token, attempt,
                          receipt_id, created_at, updated_at, committed_at
                """,
                (
                    self._database.deployment_namespace,
                    transaction_id,
                    action,
                    key,
                    request_hash,
                    DeliveryTransactionState.CLAIMED,
                    owner_id,
                    claim_token,
                    1,
                    now,
                    now,
                ),
            ).fetchone()
            if inserted is not None:
                return DeliveryClaimResult(
                    type=DeliveryClaimResultType.CLAIMED,
                    transaction=_transaction_from_row(inserted),
                )

            existing = connection.execute(
                """
                SELECT deployment_namespace, id, action, idempotency_key,
                       request_hash, state, owner_id, claim_token, attempt,
                       receipt_id, created_at, updated_at, committed_at
                FROM delivery_transactions
                WHERE deployment_namespace = %s AND action = %s
                  AND idempotency_key = %s
                FOR UPDATE
                """,
                (self._database.deployment_namespace, action, key),
            ).fetchone()
            if existing is None:
                raise RuntimeError("delivery transaction disappeared before replay read")
            transaction = _transaction_from_row(existing)
            if transaction.request_hash != request_hash:
                return DeliveryClaimResult(
                    type=DeliveryClaimResultType.CONFLICT,
                    transaction=transaction,
                )
            if transaction.state is DeliveryTransactionState.COMMITTED:
                return DeliveryClaimResult(
                    type=DeliveryClaimResultType.REPLAY,
                    transaction=transaction,
                    receipt=_receipt_for_transaction(connection, transaction),
                )
            return DeliveryClaimResult(
                type=DeliveryClaimResultType.IN_PROGRESS,
                transaction=transaction,
            )

    def mark_processing(self, transaction_id: UUID, claim_token: str) -> None:
        self._mark_active(transaction_id, claim_token, DeliveryTransactionState.PROCESSING)

    def mark_unknown(self, transaction_id: UUID, claim_token: str) -> None:
        self._mark_active(transaction_id, claim_token, DeliveryTransactionState.UNKNOWN)

    def mark_failed(self, transaction_id: UUID, claim_token: str) -> None:
        self._mark_active(transaction_id, claim_token, DeliveryTransactionState.FAILED)

    def commit(
        self,
        transaction_id: UUID,
        claim_token: str,
        receipt: IdempotencyRecord,
        audit: DeliveryAuditRecord,
    ) -> DeliveryCommitResult:
        claim_token = _required_text(claim_token, "claim_token")
        with self._database.connect() as connection:
            row = _locked_transaction(
                connection, self._database.deployment_namespace, transaction_id
            )
            transaction = _transaction_from_row(row)
            _require_owner(transaction, claim_token)
            validate_delivery_transaction_transition(
                transaction.state, DeliveryTransactionState.COMMITTED
            )
            _validate_commit_identity(transaction, receipt, audit)

            stored_receipt = _insert_or_load_receipt(
                connection, self._database.deployment_namespace, receipt
            )
            connection.execute(
                """
                INSERT INTO control_plane_delivery_audit_records (
                    deployment_namespace, session_id, action, status, status_code,
                    policy_profile, idempotency_key, result_metadata, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self._database.deployment_namespace,
                    audit.session_id,
                    audit.action,
                    audit.status,
                    audit.status_code,
                    audit.policy_profile,
                    audit.idempotency_key,
                    Jsonb(audit.result_metadata),
                    audit.created_at,
                ),
            )
            committed_at = datetime.now(UTC)
            committed = connection.execute(
                """
                UPDATE delivery_transactions
                SET state = %s, receipt_id = %s, updated_at = %s, committed_at = %s
                WHERE deployment_namespace = %s AND id = %s
                RETURNING deployment_namespace, id, action, idempotency_key,
                          request_hash, state, owner_id, claim_token, attempt,
                          receipt_id, created_at, updated_at, committed_at
                """,
                (
                    DeliveryTransactionState.COMMITTED,
                    stored_receipt.idempotency_key,
                    committed_at,
                    committed_at,
                    self._database.deployment_namespace,
                    transaction_id,
                ),
            ).fetchone()
            if committed is None:
                raise DeliveryTransactionStateError(
                    "delivery transaction disappeared during commit"
                )
            return DeliveryCommitResult(
                transaction=_transaction_from_row(committed),
                receipt=stored_receipt,
                audit=audit,
            )

    def replay(
        self,
        *,
        namespace: str,
        action: str,
        key: str,
        request_hash: str,
    ) -> DeliveryReplayResult:
        self._require_namespace(namespace)
        action = _required_text(action, "action")
        key = _required_text(key, "key")
        request_hash = _required_text(request_hash, "request_hash")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT deployment_namespace, id, action, idempotency_key,
                       request_hash, state, owner_id, claim_token, attempt,
                       receipt_id, created_at, updated_at, committed_at
                FROM delivery_transactions
                WHERE deployment_namespace = %s AND action = %s
                  AND idempotency_key = %s
                """,
                (self._database.deployment_namespace, action, key),
            ).fetchone()
            if row is None:
                return DeliveryReplayResult(type=DeliveryReplayResultType.NOT_FOUND)
            transaction = _transaction_from_row(row)
            if transaction.request_hash != request_hash:
                return DeliveryReplayResult(
                    type=DeliveryReplayResultType.CONFLICT,
                    transaction=transaction,
                )
            if transaction.state is DeliveryTransactionState.COMMITTED:
                return DeliveryReplayResult(
                    type=DeliveryReplayResultType.REPLAY,
                    transaction=transaction,
                    receipt=_receipt_for_transaction(connection, transaction),
                )
            result_type = {
                DeliveryTransactionState.CLAIMED: DeliveryReplayResultType.IN_PROGRESS,
                DeliveryTransactionState.PROCESSING: DeliveryReplayResultType.IN_PROGRESS,
                DeliveryTransactionState.UNKNOWN: DeliveryReplayResultType.UNKNOWN,
                DeliveryTransactionState.FAILED: DeliveryReplayResultType.FAILED,
            }[transaction.state]
            return DeliveryReplayResult(type=result_type, transaction=transaction)

    def get_state(self, transaction_id: UUID) -> DeliveryTransactionRecord:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT deployment_namespace, id, action, idempotency_key,
                       request_hash, state, owner_id, claim_token, attempt,
                       receipt_id, created_at, updated_at, committed_at
                FROM delivery_transactions
                WHERE deployment_namespace = %s AND id = %s
                """,
                (self._database.deployment_namespace, transaction_id),
            ).fetchone()
        if row is None:
            raise DeliveryTransactionNotFoundError(str(transaction_id))
        return _transaction_from_row(row)

    def _mark_active(
        self,
        transaction_id: UUID,
        claim_token: str,
        target: DeliveryTransactionState,
    ) -> None:
        claim_token = _required_text(claim_token, "claim_token")
        with self._database.connect() as connection:
            row = _locked_transaction(
                connection, self._database.deployment_namespace, transaction_id
            )
            transaction = _transaction_from_row(row)
            _require_owner(transaction, claim_token)
            validate_delivery_transaction_transition(transaction.state, target)
            connection.execute(
                """
                UPDATE delivery_transactions
                SET state = %s, updated_at = %s
                WHERE deployment_namespace = %s AND id = %s
                """,
                (
                    target,
                    datetime.now(UTC),
                    self._database.deployment_namespace,
                    transaction_id,
                ),
            )

    def _require_namespace(self, namespace: str) -> None:
        if _required_text(namespace, "namespace") != self._database.deployment_namespace:
            raise ValueError("delivery transaction namespace does not match store namespace")


def _locked_transaction(connection: Any, namespace: str, transaction_id: UUID) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT deployment_namespace, id, action, idempotency_key, request_hash,
               state, owner_id, claim_token, attempt, receipt_id,
               created_at, updated_at, committed_at
        FROM delivery_transactions
        WHERE deployment_namespace = %s AND id = %s
        FOR UPDATE
        """,
        (namespace, transaction_id),
    ).fetchone()
    if row is None:
        raise DeliveryTransactionNotFoundError(str(transaction_id))
    return cast(dict[str, Any], row)


def _require_owner(transaction: DeliveryTransactionRecord, claim_token: str) -> None:
    if transaction.claim_token != claim_token:
        raise DeliveryTransactionOwnershipError("delivery claim token is not current")


def _validate_commit_identity(
    transaction: DeliveryTransactionRecord,
    receipt: IdempotencyRecord,
    audit: DeliveryAuditRecord,
) -> None:
    if (
        receipt.action != transaction.action
        or receipt.idempotency_key != transaction.idempotency_key
        or receipt.request_hash != transaction.request_hash
    ):
        raise DeliveryTransactionInvariantError("receipt identity does not match transaction")
    if audit.action != transaction.action:
        raise DeliveryTransactionInvariantError("audit action does not match transaction")
    if audit.idempotency_key is not None and audit.idempotency_key != transaction.idempotency_key:
        raise DeliveryTransactionInvariantError("audit idempotency key does not match transaction")


def _insert_or_load_receipt(
    connection: Any,
    namespace: str,
    receipt: IdempotencyRecord,
) -> IdempotencyRecord:
    inserted = connection.execute(
        """
        INSERT INTO control_plane_idempotency_records (
            deployment_namespace, action, idempotency_key, request_hash,
            status_code, response_body, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (deployment_namespace, action, idempotency_key) DO NOTHING
        RETURNING action, idempotency_key, request_hash, status_code,
                  response_body, created_at
        """,
        (
            namespace,
            receipt.action,
            receipt.idempotency_key,
            receipt.request_hash,
            receipt.status_code,
            Jsonb(receipt.response_body),
            receipt.created_at,
        ),
    ).fetchone()
    if inserted is not None:
        return _receipt_from_row(inserted)
    existing = connection.execute(
        """
        SELECT action, idempotency_key, request_hash, status_code,
               response_body, created_at
        FROM control_plane_idempotency_records
        WHERE deployment_namespace = %s AND action = %s
          AND idempotency_key = %s
        FOR UPDATE
        """,
        (namespace, receipt.action, receipt.idempotency_key),
    ).fetchone()
    if existing is None:
        raise DeliveryTransactionInvariantError("receipt disappeared during transaction commit")
    stored = _receipt_from_row(existing)
    if stored.request_hash != receipt.request_hash:
        raise DeliveryTransactionConflictError("receipt identity was reused with different request")
    return stored


def _receipt_for_transaction(
    connection: Any, transaction: DeliveryTransactionRecord
) -> IdempotencyRecord:
    if transaction.receipt_id is None:
        raise DeliveryTransactionInvariantError("committed transaction has no receipt reference")
    row = connection.execute(
        """
        SELECT action, idempotency_key, request_hash, status_code,
               response_body, created_at
        FROM control_plane_idempotency_records
        WHERE deployment_namespace = %s AND action = %s
          AND idempotency_key = %s
        """,
        (
            transaction.deployment_namespace,
            transaction.action,
            transaction.receipt_id,
        ),
    ).fetchone()
    if row is None:
        raise DeliveryTransactionInvariantError("committed transaction receipt is missing")
    return _receipt_from_row(row)


def _transaction_from_row(row: dict[str, Any]) -> DeliveryTransactionRecord:
    return DeliveryTransactionRecord(
        transaction_id=UUID(str(row["id"])),
        deployment_namespace=str(row["deployment_namespace"]),
        action=str(row["action"]),
        idempotency_key=str(row["idempotency_key"]),
        request_hash=str(row["request_hash"]),
        state=DeliveryTransactionState(str(row["state"])),
        owner_id=str(row["owner_id"]),
        claim_token=str(row["claim_token"]),
        attempt=int(row["attempt"]),
        receipt_id=row["receipt_id"],
        created_at=_aware_datetime(row["created_at"]),
        updated_at=_aware_datetime(row["updated_at"]),
        committed_at=_aware_datetime(row["committed_at"]) if row["committed_at"] else None,
    )


def _receipt_from_row(row: dict[str, Any]) -> IdempotencyRecord:
    response_body = row["response_body"]
    if not isinstance(response_body, dict):
        raise DeliveryTransactionInvariantError("receipt response_body must be a JSON object")
    return IdempotencyRecord(
        action=str(row["action"]),
        idempotency_key=str(row["idempotency_key"]),
        request_hash=str(row["request_hash"]),
        status_code=int(row["status_code"]),
        response_body=json.loads(json.dumps(response_body)),
        created_at=_aware_datetime(row["created_at"]),
    )


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DeliveryTransactionInvariantError(
            "delivery transaction timestamp must be timezone-aware"
        )
    return value


def _required_text(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = value.strip()
    if not value:
        raise ValueError(f"{field} must not be blank")
    return value
