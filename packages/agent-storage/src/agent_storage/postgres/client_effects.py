"""PostgreSQL adapter for durable client effects, receipts and resume.

Effect + continuation + scheduled event commit in one transaction;
receipt + terminal status + parent resume command commit in one
transaction. Replays return the stored outcome without duplicating
events or commands (ADR-CLIENT-01).
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid5

from agent_core.domain.client_effects import (
    ClientEffectContinuation,
    ClientEffectError,
    ClientEffectFenceError,
    ClientEffectIdempotencyConflict,
    ClientEffectReceipt,
    ClientEffectReceiptConflict,
    ClientEffectRequest,
    ClientEffectStatus,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import (
    ClientEffectId,
    ClientSessionId,
    SessionId,
    TaskId,
    ToolCallId,
)
from agent_core.ports.client_effect_dispatch import (
    ClientEffectDispatchPort,
    ClientEffectScheduleOutcome,
)
from agent_core.ports.client_effect_receipts import (
    ClientEffectReceiptPort,
    ClientReceiptAcceptance,
)
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import append_event_in_transaction

_CLIENT_EFFECT_NAMESPACE = UUID("2f6b7c5e-9a34-4f17-8b2d-5c1e0a9d7b3a")


class PostgresClientEffectDispatch(ClientEffectDispatchPort):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._namespace = self._database.deployment_namespace

    def schedule(
        self,
        request: ClientEffectRequest,
        *,
        continuation: ClientEffectContinuation,
        session_id: SessionId,
    ) -> ClientEffectScheduleOutcome:
        if request.parent_session_id != session_id:
            raise ClientEffectError("effect parent session does not match event stream")
        if (
            continuation.effect_id != request.effect_id
            or continuation.task_id != request.task_id
            or continuation.run_id != request.run_id
            or continuation.tool_call_id != request.tool_call_id
            or continuation.action_name != request.action_name
        ):
            raise ClientEffectError("effect continuation does not match the request")
        with self._database.connect() as connection:
            existing = self._by_idempotency_key(connection, request.idempotency_key)
            if existing is not None:
                if existing["request_digest"] != request.request_digest:
                    raise ClientEffectIdempotencyConflict(
                        "idempotency key reused with a different request digest"
                    )
                return ClientEffectScheduleOutcome(
                    effect=_request_from_row(existing), created=False
                )
            inserted = connection.execute(
                """
                INSERT INTO client_effects (
                    deployment_namespace, effect_id, task_id, parent_session_id, run_id,
                    client_session_id, tool_call_id, action_name,
                    arguments_json, action_contract_digest,
                    client_binding_digest, fence_hash, expected_ui_revision,
                    idempotency_key, request_digest, status,
                    requested_at, expires_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'pending', %s, %s
                )
                ON CONFLICT DO NOTHING
                RETURNING effect_id
                """,
                (
                    self._namespace,
                    request.effect_id,
                    request.task_id,
                    request.parent_session_id,
                    request.run_id,
                    request.client_session_id,
                    request.tool_call_id,
                    request.action_name,
                    Jsonb(request.arguments),
                    request.action_contract_digest,
                    request.client_binding_digest,
                    request.fence_hash,
                    request.expected_ui_revision,
                    request.idempotency_key,
                    request.request_digest,
                    request.requested_at,
                    request.expires_at,
                ),
            ).fetchone()
            if inserted is None:
                raced = self._by_idempotency_key(connection, request.idempotency_key)
                if raced is None or raced["request_digest"] != request.request_digest:
                    raise ClientEffectIdempotencyConflict(
                        "effect identity raced with different content"
                    )
                return ClientEffectScheduleOutcome(effect=_request_from_row(raced), created=False)
            connection.execute(
                """
                INSERT INTO client_effect_continuations (
                    deployment_namespace, effect_id, task_id, run_id,
                    tool_call_id, action_name, assistant_message,
                    model_calls_used, tool_calls_executed, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self._namespace,
                    continuation.effect_id,
                    continuation.task_id,
                    continuation.run_id,
                    continuation.tool_call_id,
                    continuation.action_name,
                    continuation.assistant_message,
                    continuation.model_calls_used,
                    continuation.tool_calls_executed,
                    continuation.created_at,
                ),
            )
            _append_client_event(
                connection,
                self._namespace,
                session_id,
                EventType.CLIENT_EFFECT_SCHEDULED,
                EventActor.TOOL,
                {
                    "attempt_number": 1,
                    "tool_name": request.action_name,
                    "tool_call_id": str(request.tool_call_id),
                    "client_effect_id": str(request.effect_id),
                    "action_name": request.action_name,
                    "arguments": request.arguments,
                    "action_contract_digest": request.action_contract_digest,
                    "client_binding_digest": request.client_binding_digest,
                    "expected_ui_revision": request.expected_ui_revision,
                    "idempotency_key": request.idempotency_key,
                    "request_digest": request.request_digest,
                },
                idempotency_key=f"client-effect-scheduled:{request.effect_id}",
            )
        return ClientEffectScheduleOutcome(effect=request, created=True)

    def get_effect(self, effect_id: ClientEffectId) -> ClientEffectRequest | None:
        with self._database.connect() as connection:
            row = self._by_effect_id(connection, effect_id)
        return None if row is None else _request_from_row(row)

    def list_pending(
        self, client_session_id: ClientSessionId, *, limit: int = 50
    ) -> tuple[ClientEffectRequest, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM client_effects
                WHERE deployment_namespace = %s AND client_session_id = %s
                    AND status = 'pending'
                ORDER BY requested_at
                LIMIT %s
                """,
                (self._namespace, client_session_id, limit),
            ).fetchall()
        return tuple(_request_from_row(row) for row in rows)

    def mark_delivered(self, effect_id: ClientEffectId) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE client_effects
                SET status = 'delivered'
                WHERE deployment_namespace = %s AND effect_id = %s
                    AND status = 'pending'
                """,
                (self._namespace, effect_id),
            )

    def load_continuation(self, effect_id: ClientEffectId) -> ClientEffectContinuation | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM client_effect_continuations
                WHERE deployment_namespace = %s AND effect_id = %s
                """,
                (self._namespace, effect_id),
            ).fetchone()
        if row is None:
            return None
        return ClientEffectContinuation(
            effect_id=ClientEffectId(UUID(str(row["effect_id"]))),
            task_id=TaskId(UUID(str(row["task_id"]))),
            run_id=row["run_id"],
            tool_call_id=ToolCallId(UUID(str(row["tool_call_id"]))),
            action_name=row["action_name"],
            assistant_message=row["assistant_message"],
            model_calls_used=int(row["model_calls_used"]),
            tool_calls_executed=int(row["tool_calls_executed"]),
            created_at=row["created_at"],
        )

    def _by_idempotency_key(self, connection: Any, key: str) -> Any:
        return connection.execute(
            """
            SELECT * FROM client_effects
            WHERE deployment_namespace = %s AND idempotency_key = %s
            """,
            (self._namespace, key),
        ).fetchone()

    def _by_effect_id(self, connection: Any, effect_id: ClientEffectId) -> Any:
        return connection.execute(
            """
            SELECT * FROM client_effects
            WHERE deployment_namespace = %s AND effect_id = %s
            """,
            (self._namespace, effect_id),
        ).fetchone()


class PostgresClientEffectReceipts(ClientEffectReceiptPort):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._namespace = self._database.deployment_namespace

    def accept_receipt(
        self,
        receipt: ClientEffectReceipt,
        *,
        request_fence_hash: str,
        session_id: SessionId,
    ) -> ClientReceiptAcceptance:
        now = datetime.now(UTC)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM client_effects
                WHERE deployment_namespace = %s AND effect_id = %s
                FOR UPDATE
                """,
                (self._namespace, receipt.effect_id),
            ).fetchone()
            if row is None:
                raise ClientEffectError("client effect not found")
            if UUID(str(row["parent_session_id"])) != session_id:
                raise ClientEffectError("effect parent session does not match resume stream")
            if row["fence_hash"] != request_fence_hash:
                raise ClientEffectFenceError("stale client fence rejected")
            existing_receipt = connection.execute(
                """
                SELECT * FROM client_effect_receipts
                WHERE deployment_namespace = %s AND effect_id = %s
                """,
                (self._namespace, receipt.effect_id),
            ).fetchone()
            if existing_receipt is not None:
                if (
                    existing_receipt["idempotency_key"] != receipt.idempotency_key
                    or existing_receipt["request_digest"] != receipt.request_digest
                ):
                    raise ClientEffectReceiptConflict(
                        "effect already resolved by a different receipt"
                    )
                if existing_receipt["status"] != receipt.status.value:
                    raise ClientEffectReceiptConflict(
                        "effect terminal receipt is semantically inconsistent"
                    )
                if dict(existing_receipt["result_json"]) != receipt.result:
                    raise ClientEffectReceiptConflict(
                        "effect terminal receipt result is semantically inconsistent"
                    )
                stored = _receipt_from_row(existing_receipt)
                return ClientReceiptAcceptance(
                    receipt=stored,
                    effect=_request_from_row(row),
                    resume_command_id=self._resume_command_id(receipt.effect_id),
                    replayed=True,
                )
            active_lease = connection.execute(
                """
                SELECT fence_hash FROM client_control_leases
                WHERE deployment_namespace = %s AND task_id = %s AND run_id = %s
                    AND client_session_id = %s AND released_at IS NULL
                    AND expires_at > %s
                FOR SHARE
                """,
                (
                    self._namespace,
                    row["task_id"],
                    row["run_id"],
                    row["client_session_id"],
                    now,
                ),
            ).fetchone()
            if active_lease is None or active_lease["fence_hash"] != row["fence_hash"]:
                raise ClientEffectFenceError("client controller lease is no longer active")
            request = _request_from_row(row)
            session_row = connection.execute(
                """
                SELECT ui_revision FROM client_sessions
                WHERE deployment_namespace = %s AND client_session_id = %s
                """,
                (self._namespace, request.client_session_id),
            ).fetchone()
            current_ui_revision = int(session_row["ui_revision"]) if session_row is not None else -1
            request.ensure_receiptable(current_ui_revision=current_ui_revision, now=now)
            connection.execute(
                """
                INSERT INTO client_effect_receipts (
                    deployment_namespace, effect_id, receipt_id,
                    idempotency_key, request_digest, status, result_json,
                    received_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self._namespace,
                    receipt.effect_id,
                    receipt.receipt_id,
                    receipt.idempotency_key,
                    receipt.request_digest,
                    receipt.status.value,
                    Jsonb(receipt.result),
                    receipt.received_at,
                ),
            )
            connection.execute(
                """
                UPDATE client_effects
                SET status = %s
                WHERE deployment_namespace = %s AND effect_id = %s
                """,
                (receipt.status.value, self._namespace, receipt.effect_id),
            )
            resume_command_id = str(
                uuid5(
                    _CLIENT_EFFECT_NAMESPACE,
                    f"client-effect-resume:{receipt.effect_id}",
                )
            )
            _append_client_event(
                connection,
                self._namespace,
                session_id,
                EventType.CLIENT_EFFECT_RECEIPT_ACCEPTED,
                EventActor.TOOL,
                {
                    "client_effect_id": str(receipt.effect_id),
                    "receipt_id": str(receipt.receipt_id),
                    "status": receipt.status.value,
                    "request_digest": receipt.request_digest,
                    "replayed": False,
                },
                idempotency_key=f"client-effect-receipt:{receipt.effect_id}",
            )
            _append_client_event(
                connection,
                self._namespace,
                session_id,
                EventType.SESSION_COMMAND_ACCEPTED,
                EventActor.HARNESS,
                {
                    "command_id": resume_command_id,
                    "session_id": str(session_id),
                    "kind": "resume",
                    "expected_revision": _anchored_revision(
                        connection, self._namespace, session_id
                    ),
                    "idempotency_key": f"client-effect-resume:{receipt.effect_id}",
                    "payload": {
                        "client_effect_result": {
                            "client_effect_id": str(receipt.effect_id),
                            "tool_call_id": str(request.tool_call_id),
                            "action_name": request.action_name,
                            "status": receipt.status.value,
                            "result": receipt.result,
                        }
                    },
                    "fingerprint": _resume_fingerprint(session_id, receipt.effect_id),
                },
                idempotency_key=f"client-effect-resume:{receipt.effect_id}",
            )
        return ClientReceiptAcceptance(
            receipt=receipt,
            effect=request.model_copy(update={"status": ClientEffectStatus(receipt.status.value)}),
            resume_command_id=resume_command_id,
            replayed=False,
        )

    @staticmethod
    def _resume_command_id(effect_id: ClientEffectId) -> str:
        return str(uuid5(_CLIENT_EFFECT_NAMESPACE, f"client-effect-resume:{effect_id}"))


def _append_client_event(
    connection: Any,
    namespace: str,
    session_id: SessionId,
    event_type: EventType,
    actor: EventActor,
    payload: dict[str, object],
    *,
    idempotency_key: str,
) -> None:
    current = connection.execute(
        """
        SELECT COALESCE(MAX(sequence), -1) AS current_sequence
        FROM session_events
        WHERE deployment_namespace = %s AND session_id = %s
        """,
        (namespace, str(session_id)),
    ).fetchone()
    assert current is not None
    event = SessionEvent.create(
        session_id=session_id,
        sequence=int(current["current_sequence"]) + 1,
        event_type=event_type,
        actor=actor,
        payload=payload,
        created_at=datetime.now(UTC),
        idempotency_key=idempotency_key,
    )
    append_event_in_transaction(connection, namespace, event)


def _anchored_revision(connection: Any, namespace: str, session_id: SessionId) -> int:
    row = connection.execute(
        """
        SELECT COALESCE(MAX(sequence), 0) AS anchored
        FROM session_events
        WHERE deployment_namespace = %s AND session_id = %s
            AND event_type = 'client_effect_scheduled'
        """,
        (namespace, str(session_id)),
    ).fetchone()
    assert row is not None
    return int(row["anchored"])


def _resume_fingerprint(session_id: SessionId, effect_id: ClientEffectId) -> str:
    return sha256(f"{session_id}:client-effect:{effect_id}".encode()).hexdigest()


def _request_from_row(row: Any) -> ClientEffectRequest:
    return ClientEffectRequest(
        effect_id=ClientEffectId(UUID(str(row["effect_id"]))),
        task_id=TaskId(UUID(str(row["task_id"]))),
        parent_session_id=SessionId(UUID(str(row["parent_session_id"]))),
        run_id=row["run_id"],
        client_session_id=ClientSessionId(UUID(str(row["client_session_id"]))),
        tool_call_id=ToolCallId(UUID(str(row["tool_call_id"]))),
        action_name=row["action_name"],
        arguments=dict(row["arguments_json"]),
        action_contract_digest=row["action_contract_digest"],
        client_binding_digest=row["client_binding_digest"],
        fence_hash=row["fence_hash"],
        expected_ui_revision=int(row["expected_ui_revision"]),
        idempotency_key=row["idempotency_key"],
        requested_at=row["requested_at"],
        expires_at=row["expires_at"],
        status=ClientEffectStatus(row["status"]),
    )


def _receipt_from_row(row: Any) -> ClientEffectReceipt:
    return ClientEffectReceipt(
        receipt_id=UUID(str(row["receipt_id"])),
        effect_id=ClientEffectId(UUID(str(row["effect_id"]))),
        idempotency_key=row["idempotency_key"],
        request_digest=row["request_digest"],
        status=ClientEffectStatus(row["status"]),
        result=dict(row["result_json"]),
        received_at=row["received_at"],
    )
