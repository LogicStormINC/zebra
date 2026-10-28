"""Reconcile receipted or expired browser waits without replaying browser actions."""

from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from typing import Any
from uuid import UUID, uuid5

from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from psycopg.conninfo import make_conninfo
from psycopg.errors import LockNotAvailable, QueryCanceled

from agent_storage.postgres.client_effects import _append_client_event
from agent_storage.postgres.database import PostgresDatabase

_NAMESPACE = UUID("2f6b7c5e-9a34-4f17-8b2d-5c1e0a9d7b3a")


class ClientEffectRecovery:
    """Bounded maintenance for a waiting Session; immutable evidence is preserved."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(
            make_conninfo(
                dsn, connect_timeout=2, options="-c statement_timeout=1500 -c lock_timeout=100"
            ),
            deployment_namespace=deployment_namespace,
        )
        self._cursor: SessionId | None = None

    def reconcile(self, *, session_id: SessionId | None = None, dry_run: bool = False) -> int:
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            rows = connection.execute(
                """SELECT session_id FROM session_projections
                WHERE deployment_namespace=%s AND status='waiting_client_effect'
                  AND (%s::uuid IS NULL OR session_id=%s)
                  AND (%s::uuid IS NULL OR session_id>%s)
                ORDER BY session_id LIMIT 32""",
                (
                    namespace,
                    session_id,
                    session_id,
                    None if session_id else self._cursor,
                    None if session_id else self._cursor,
                ),
            ).fetchall()
        if session_id is None and not rows:
            self._cursor = None
        count = 0
        deadline = monotonic() + 5
        for row in rows:
            if monotonic() >= deadline:
                break
            selected = SessionId(row["session_id"])
            if session_id is None:
                self._cursor = selected
            try:
                with self._database.connect() as connection:
                    count += self._recover(connection, selected, dry_run)
            except (LockNotAvailable, QueryCanceled):
                if session_id is not None:
                    raise
                continue
        return count

    def _recover(self, connection: Any, session_id: SessionId, dry_run: bool) -> int:
        namespace = self._database.deployment_namespace
        # Receipt writers lock the effect before the stream; keep that lock order.
        connection.execute(
            """SELECT effect_id FROM client_effects
            WHERE deployment_namespace=%s AND parent_session_id=%s
            ORDER BY effect_id FOR UPDATE""",
            (namespace, session_id),
        ).fetchall()
        # Share the stream lock used by append_event_in_transaction.
        connection.execute(
            """SELECT session_id FROM session_streams
            WHERE deployment_namespace=%s AND session_id=%s FOR UPDATE""",
            (namespace, session_id),
        ).fetchone()
        rows = connection.execute(
            """SELECT * FROM session_events WHERE deployment_namespace=%s AND session_id=%s
            ORDER BY sequence""",
            (namespace, session_id),
        ).fetchall()
        events = [SessionEvent.model_validate(row) for row in rows]
        boundaries = [
            e
            for e in events
            if e.event_type
            in {
                EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
                EventType.SESSION_RESUMED,
                EventType.SESSION_SUSPENDED,
                EventType.TURN_COMPLETED,
                EventType.TURN_FAILED,
                EventType.TURN_CANCELLED,
                EventType.USER_MESSAGE_RECEIVED,
                EventType.APPROVAL_REQUESTED,
                EventType.CLARIFICATION_REQUESTED,
                EventType.SESSION_COMPLETED,
                EventType.SESSION_FAILED,
                EventType.SESSION_CANCELLED,
            }
        ]
        if (
            not boundaries
            or boundaries[-1].event_type is not EventType.SESSION_WAITING_FOR_CLIENT_EFFECT
        ):
            return 0
        waiting = boundaries[-1]
        if any(
            e.sequence > waiting.sequence
            and e.event_type is EventType.SESSION_COMMAND_ACCEPTED
            and e.payload.get("kind") in {"stop", "cancel", "suspend"}
            for e in events
        ):
            return 0
        active = connection.execute(
            """SELECT 1 FROM worker_leases WHERE deployment_namespace=%s AND session_id=%s
            AND released_at IS NULL AND expires_at>NOW()""",
            (namespace, session_id),
        ).fetchone()
        if active:
            return 0
        count = 0
        for effect_id in waiting.payload.get("client_effect_ids", []):
            effect = connection.execute(
                """SELECT e.*, r.status AS receipt_status, r.result_json AS receipt_result,
                    r.request_digest AS receipt_digest
                FROM client_effects e LEFT JOIN client_effect_receipts r
                ON r.deployment_namespace=e.deployment_namespace AND r.effect_id=e.effect_id
                WHERE e.deployment_namespace=%s AND e.parent_session_id=%s AND e.effect_id=%s
                FOR UPDATE OF e""",
                (namespace, session_id, effect_id),
            ).fetchone()
            if effect is None:
                continue
            result = self._result(effect)
            if result is None:
                continue
            commands = [
                e
                for e in events
                if e.event_type is EventType.SESSION_COMMAND_ACCEPTED
                and e.actor is EventActor.HARNESS
                and e.payload.get("payload", {})
                .get("client_effect_result", {})
                .get("client_effect_id")
                == str(effect_id)
            ]
            # Repair only the known legacy generator. Canonical or unknown commands
            # are never silently replaced (including permanently rejected commands).
            legacy = sha256(f"{session_id}:client-effect:{effect_id}".encode()).hexdigest()
            if any(e.payload.get("fingerprint") != legacy for e in commands):
                continue
            if any(e.payload.get("payload") != {"client_effect_result": result} for e in commands):
                continue
            key = f"client-effect-resume:recovery:{effect_id}"
            command = SessionCommand(
                command_id=uuid5(_NAMESPACE, key),
                session_id=session_id,
                kind=SessionCommandKind.RESUME,
                expected_revision=waiting.sequence,
                idempotency_key=key,
                payload={"client_effect_result": result},
            )
            if not dry_run:
                _append_client_event(
                    connection,
                    namespace,
                    session_id,
                    EventType.SESSION_COMMAND_ACCEPTED,
                    EventActor.HARNESS,
                    command.event_payload(),
                    idempotency_key=key,
                )
                if effect["receipt_status"] is None:
                    connection.execute(
                        """UPDATE client_effects SET status='expired'
                        WHERE deployment_namespace=%s AND effect_id=%s""",
                        (namespace, effect_id),
                    )
            count += 1
        return count

    @staticmethod
    def _result(effect: Any) -> dict[str, object] | None:
        status = effect["receipt_status"]
        if status is not None:
            if effect["receipt_digest"] != effect["request_digest"]:
                return None
            result = effect["receipt_result"]
        elif effect["status"] in {"pending", "delivered", "expired"} and effect[
            "expires_at"
        ] <= datetime.now(UTC):
            status, result = "expired", {"reason": "browser_action_deadline_exceeded"}
        else:
            return None
        return {
            "client_effect_id": str(effect["effect_id"]),
            "tool_call_id": str(effect["tool_call_id"]),
            "action_name": effect["action_name"],
            "status": status,
            "result": result,
        }
