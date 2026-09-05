"""Short fenced Broker Outbox transactions. No network or execution authority."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID

from agent_core.contracts.broker_envelope import ZebraCommandEnvelope, parse_broker_envelope
from agent_core.domain.events import EventType, SessionEvent
from pydantic import ValidationError

from agent_storage.postgres.command_wakeup import (
    _canonical_json,
    _envelope,
    _scope_from_binding,
    command_scope_key,
)
from agent_storage.postgres.command_wakeup_discovery import _database
from agent_storage.postgres.command_wakeup_recovery_proof import recovery_approval

MAX_RELAY_BATCH = 32


@dataclass(frozen=True)
class RelayClaim:
    deployment_namespace: str
    message_id: UUID
    owner: str
    fence: int
    body: bytes
    lease_expires_at: datetime
    publish_attempt: int


def _owner(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 128
        or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)
    ):
        raise ValueError("invalid relay owner")


def _ttl(value: timedelta) -> None:
    if not isinstance(value, timedelta) or not timedelta(0) < value <= timedelta(minutes=5):
        raise ValueError("relay lease ttl must be positive and at most five minutes")


def _now(connection: Any) -> datetime:
    value: datetime = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    return value.astimezone(UTC)


def _validated_body(connection: Any, namespace: str, row: dict[str, Any]) -> bytes:
    body = _canonical_json(row["envelope_json"]).encode("utf-8")
    envelope = parse_broker_envelope(body)
    if not isinstance(envelope, ZebraCommandEnvelope):
        raise ValueError("wrong envelope type")
    if (
        sha256(body).hexdigest() != row["envelope_digest"]
        or envelope.deployment_namespace != namespace
        or envelope.message_id != str(row["message_id"])
        or envelope.message_type != row["message_type"]
        or envelope.schema_version != row["schema_version"]
        or envelope.aggregate_id != str(row["aggregate_id"])
        or envelope.operation_id != str(row["operation_id"])
        or envelope.wake_generation != row["wake_generation"]
        or command_scope_key(envelope.scope) != row["scope_key"]
    ):
        raise ValueError("outbox identity mismatch")
    event_row = connection.execute(
        """SELECT event_id, session_id, sequence, event_type, payload, actor,
                  created_at, causation_id, correlation_id, idempotency_key,
                  policy_version, model_profile FROM session_events
           WHERE deployment_namespace = %s AND event_id = %s""",
        (namespace, UUID(envelope.accepted_event_id)),
    ).fetchone()
    if event_row is None:
        raise ValueError("missing canonical Event")
    event = SessionEvent.model_validate(event_row)
    if event.event_type is not EventType.SESSION_COMMAND_ACCEPTED:
        raise ValueError("not a canonical command")
    scope = _scope_from_binding(connection, namespace, event)
    if envelope != _envelope(namespace, event, scope, generation=envelope.wake_generation):
        raise ValueError("outbox differs from canonical Event")
    recovery_approval(connection, envelope)
    return body


def claim_relay_batch(
    dsn: str,
    *,
    deployment_namespace: str,
    owner: str,
    batch_size: int = 16,
    ttl: timedelta = timedelta(seconds=30),
    scope_mode: Literal["all", "broker"] = "all",
) -> tuple[RelayClaim, ...]:
    """Claim a bounded batch; poison rows are terminal with a fixed diagnostic."""
    _owner(owner)
    _ttl(ttl)
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_RELAY_BATCH:
        raise ValueError("relay batch size must be an integer between 1 and 32")
    if scope_mode not in ("all", "broker"):
        raise ValueError("invalid relay scope mode")
    claims = []
    with _database(dsn, deployment_namespace).connect() as connection:
        connection.execute("SET LOCAL lock_timeout = '5s'")
        selected_at = _now(connection)
        rows = connection.execute(
            """SELECT * FROM broker_outbox outbox WHERE deployment_namespace = %s AND (
                   (status = 'pending' AND available_at <= %s) OR
                   (status = 'publishing' AND lease_expires_at <= %s))
               AND (%s='all' OR EXISTS (
                 SELECT 1 FROM command_delivery_scope_rollouts rollout
                 WHERE rollout.deployment_namespace=outbox.deployment_namespace
                   AND rollout.scope_key=outbox.scope_key AND rollout.mode='broker'))
               ORDER BY available_at, message_id LIMIT %s FOR UPDATE SKIP LOCKED""",
            (deployment_namespace, selected_at, selected_at, scope_mode, batch_size),
        ).fetchall()
        for row in rows:
            now = _now(connection)
            if not (
                (row["status"] == "pending" and row["available_at"] <= now)
                or (
                    row["status"] == "publishing"
                    and row["lease_expires_at"] is not None
                    and row["lease_expires_at"] <= now
                )
            ):
                continue
            try:
                body = _validated_body(connection, deployment_namespace, row)
            except (ValueError, TypeError, KeyError, ValidationError):
                connection.execute(
                    """UPDATE broker_outbox SET status = 'dead',
                       last_error_code = 'invalid_outbox', relay_owner = NULL,
                       lease_expires_at = NULL
                       WHERE deployment_namespace = %s AND message_id = %s""",
                    (deployment_namespace, row["message_id"]),
                )
                continue
            # Validation may perform reads; sample again for the full claim TTL.
            expires = _now(connection) + ttl
            updated = connection.execute(
                """UPDATE broker_outbox SET status = 'publishing', relay_owner = %s,
                   relay_fence = relay_fence + 1, lease_expires_at = %s,
                   publish_attempts = publish_attempts + 1
                   WHERE deployment_namespace = %s AND message_id = %s
                   RETURNING relay_fence, publish_attempts""",
                (owner, expires, deployment_namespace, row["message_id"]),
            ).fetchone()
            assert updated is not None
            claims.append(
                RelayClaim(
                    deployment_namespace,
                    row["message_id"],
                    owner,
                    updated["relay_fence"],
                    body,
                    expires,
                    updated["publish_attempts"],
                )
            )
    return tuple(claims)


def settle_relay_claim(dsn: str, claim: RelayClaim, *, confirmed: bool) -> bool:
    """Return False for lost ownership; only confirmed publication becomes published."""
    if not isinstance(claim, RelayClaim) or type(confirmed) is not bool:
        raise ValueError("invalid relay settlement")
    _owner(claim.owner)
    with _database(dsn, claim.deployment_namespace).connect() as connection:
        connection.execute("SET LOCAL lock_timeout = '5s'")
        row = connection.execute(
            """SELECT * FROM broker_outbox
               WHERE deployment_namespace = %s AND message_id = %s FOR UPDATE""",
            (claim.deployment_namespace, claim.message_id),
        ).fetchone()
        now = _now(connection)
        if (
            row is None
            or row["status"] != "publishing"
            or row["relay_owner"] != claim.owner
            or row["relay_fence"] != claim.fence
            or row["lease_expires_at"] is None
            or row["lease_expires_at"] <= now
        ):
            return False
        # Physical delivery retries do not consume the business retry budget.
        delay = timedelta(seconds=min(60, 2 ** min(row["publish_attempts"] - 1, 6)))
        connection.execute(
            """UPDATE broker_outbox SET status = %s, published_at = %s,
               available_at = %s, last_error_code = %s, relay_owner = NULL,
               lease_expires_at = NULL
               WHERE deployment_namespace = %s AND message_id = %s""",
            (
                "published" if confirmed else "pending",
                now if confirmed else None,
                row["available_at"] if confirmed else now + delay,
                None if confirmed else "publish_unconfirmed",
                claim.deployment_namespace,
                claim.message_id,
            ),
        )
        return True
