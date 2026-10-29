"""Native atomic receipt acceptance; optional input rides the existing one resume."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.client_effects import (
    ClientEffectError,
    ClientEffectFenceError,
    ClientEffectReceipt,
    ClientEffectReceiptConflict,
    ClientEffectStatus,
)
from agent_core.domain.client_preparation import ClientPreparationContext
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import SessionId
from agent_core.ports.client_effect_receipts import ClientReceiptAcceptance
from psycopg.types.json import Jsonb

from agent_storage.postgres.client_effect_receipt_read import receipt_from_row as _receipt_from_row

if TYPE_CHECKING:
    from agent_storage.postgres.client_effects import PostgresClientEffectReceipts


def accept_receipt(
    store: PostgresClientEffectReceipts,
    receipt: ClientEffectReceipt,
    *,
    request_fence_hash: str,
    session_id: SessionId,
    preparation: ClientPreparationContext | None = None,
) -> ClientReceiptAcceptance:
    from agent_storage.postgres.client_effects import (
        _CLIENT_EFFECT_NAMESPACE,
        _anchored_revision,
        _append_client_event,
        _request_from_row,
    )

    now = datetime.now(UTC)
    with store._database.connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM client_effects
            WHERE deployment_namespace = %s AND effect_id = %s
            FOR UPDATE
            """,
            (store._namespace, receipt.effect_id),
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
            (store._namespace, receipt.effect_id),
        ).fetchone()
        if existing_receipt is not None:
            if (
                existing_receipt["idempotency_key"] != receipt.idempotency_key
                or existing_receipt["request_digest"] != receipt.request_digest
            ):
                raise ClientEffectReceiptConflict("effect already resolved by a different receipt")
            if existing_receipt["status"] != receipt.status.value:
                raise ClientEffectReceiptConflict(
                    "effect terminal receipt is semantically inconsistent"
                )
            if dict(existing_receipt["result_json"]) != receipt.result:
                raise ClientEffectReceiptConflict(
                    "effect terminal receipt result is semantically inconsistent"
                )
            if preparation is not None:
                original = connection.execute(
                    "SELECT payload->'payload' AS value FROM session_events "
                    "WHERE deployment_namespace=%s AND session_id=%s AND idempotency_key=%s "
                    "AND event_type='session_command_accepted' LIMIT 1",
                    (store._namespace, session_id, f"client-effect-resume:{receipt.effect_id}"),
                ).fetchone()
                expected = preparation.model_dump(mode="json", exclude={"input"})
                value = original["value"] if original is not None else None
                if not isinstance(value, dict) or (
                    value.get("client_preparation") != expected
                    or value.get("input") != preparation.input
                ):
                    raise ClientEffectReceiptConflict("original receipt preparation conflicts")
            stored = _receipt_from_row(existing_receipt)
            return ClientReceiptAcceptance(
                receipt=stored,
                effect=_request_from_row(row),
                resume_command_id=store._resume_command_id(receipt.effect_id),
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
                store._namespace,
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
            (store._namespace, request.client_session_id),
        ).fetchone()
        current_ui_revision = int(session_row["ui_revision"]) if session_row is not None else -1
        request.ensure_receiptable(current_ui_revision=current_ui_revision, now=now)
        continuation_payload: dict[str, object] = {
            "client_effect_result": {
                "client_effect_id": str(receipt.effect_id),
                "tool_call_id": str(request.tool_call_id),
                "action_name": request.action_name,
                "status": receipt.status.value,
                "result": receipt.result,
            }
        }
        if preparation is not None:
            if (
                preparation.task_id != request.task_id
                or preparation.run_id != request.run_id
                or preparation.client_session_id != request.client_session_id
                or preparation.operation_id != receipt.receipt_id
            ):
                raise ClientEffectReceiptConflict("receipt preparation scope conflicts")
            continuation_payload.update(
                input=preparation.input,
                client_preparation=preparation.model_dump(mode="json", exclude={"input"}),
            )
            # Validate the existing TOTAL native command budget before the first write.
            SessionCommand(
                session_id=session_id,
                kind=SessionCommandKind.RESUME,
                expected_revision=0,
                idempotency_key=f"client-effect-resume:{receipt.effect_id}",
                payload=continuation_payload,
            )
        connection.execute(
            """
            INSERT INTO client_effect_receipts (
                deployment_namespace, effect_id, receipt_id,
                idempotency_key, request_digest, status, result_json,
                received_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                store._namespace,
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
            (receipt.status.value, store._namespace, receipt.effect_id),
        )
        resume_command_id = str(
            uuid5(
                _CLIENT_EFFECT_NAMESPACE,
                f"client-effect-resume:{receipt.effect_id}",
            )
        )
        _append_client_event(
            connection,
            store._namespace,
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
            store._namespace,
            session_id,
            EventType.SESSION_COMMAND_ACCEPTED,
            EventActor.HARNESS,
            SessionCommand(
                command_id=UUID(resume_command_id),
                session_id=session_id,
                kind=SessionCommandKind.RESUME,
                expected_revision=_anchored_revision(connection, store._namespace, session_id),
                idempotency_key=f"client-effect-resume:{receipt.effect_id}",
                payload=continuation_payload,
            ).event_payload(),
            idempotency_key=f"client-effect-resume:{receipt.effect_id}",
        )
    return ClientReceiptAcceptance(
        receipt=receipt,
        effect=request.model_copy(update={"status": ClientEffectStatus(receipt.status.value)}),
        resume_command_id=resume_command_id,
        replayed=False,
    )
