"""Sanitized rejection persistence and fenced diagnostic publication; no network."""

from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from agent_core.contracts.broker_diagnostic import BrokerDiagnostic, ConsumerRole, RejectionCode
from pydantic import TypeAdapter

from agent_storage.postgres.command_wakeup_discovery import _database
from agent_storage.postgres.command_wakeup_relay import _now, _owner, _ttl


@dataclass(frozen=True)
class RejectionReceipt:
    rejection_id: UUID
    published: bool


@dataclass(frozen=True)
class RejectionClaim:
    deployment_namespace: str
    consumer_role: str
    rejection_id: UUID
    owner: str
    fence: int
    body: bytes


def validate_rejection_metadata(role: str, code: RejectionCode) -> None:
    try:
        TypeAdapter(ConsumerRole).validate_python(role)
        TypeAdapter(RejectionCode).validate_python(code)
    except ValueError:
        raise ValueError("invalid rejection metadata") from None


def record_rejection(
    dsn: str,
    *,
    deployment_namespace: str,
    consumer_role: str,
    raw: bytes,
    code: RejectionCode,
) -> RejectionReceipt:
    """Only digest/count enter SQL. No broker-claimed identities are accepted."""
    validate_rejection_metadata(consumer_role, code)
    if type(raw) is not bytes:
        raise ValueError("rejection body must be bytes")
    with _database(dsn, deployment_namespace).connect() as connection:
        connection.execute("SET LOCAL lock_timeout='5s'")
        return record_rejection_in_transaction(
            connection, deployment_namespace, consumer_role, sha256(raw).hexdigest(), len(raw), code
        )


def record_rejection_in_transaction(
    connection: Any,
    namespace: str,
    role: str,
    digest: str,
    byte_count: int,
    code: RejectionCode,
) -> RejectionReceipt:
    connection.execute(
        """INSERT INTO command_delivery_rejections (deployment_namespace, consumer_role,
           rejection_id, body_digest, byte_count, error_code) VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (deployment_namespace,consumer_role,body_digest,error_code) DO NOTHING""",
        (namespace, role, uuid4(), digest, byte_count, code),
    )
    row = connection.execute(
        """SELECT rejection_id, status, byte_count FROM command_delivery_rejections
           WHERE deployment_namespace=%s AND consumer_role=%s
             AND body_digest=%s AND error_code=%s""",
        (namespace, role, digest, code),
    ).fetchone()
    if row is None or row["byte_count"] != byte_count:
        raise ValueError("rejection receipt metadata conflict")
    return RejectionReceipt(row["rejection_id"], row["status"] == "published")


def claim_rejection(
    dsn: str,
    *,
    deployment_namespace: str,
    consumer_role: str,
    owner: str,
    ttl: timedelta = timedelta(seconds=30),
    rejection_id: UUID | None = None,
) -> RejectionClaim | None:
    validate_rejection_metadata(consumer_role, "invalid_broker_envelope")
    _owner(owner)
    _ttl(ttl)
    if rejection_id is not None and not isinstance(rejection_id, UUID):
        raise ValueError("invalid rejection receipt ID")
    with _database(dsn, deployment_namespace).connect() as connection:
        connection.execute("SET LOCAL lock_timeout='5s'")
        selected_at = _now(connection)
        row = connection.execute(
            """SELECT * FROM command_delivery_rejections WHERE deployment_namespace=%s
               AND consumer_role=%s AND (%s::uuid IS NULL OR rejection_id=%s) AND
               ((status='pending' AND available_at<=%s) OR
                (status='publishing' AND lease_expires_at<=%s))
               ORDER BY available_at,rejection_id LIMIT 1 FOR UPDATE SKIP LOCKED""",
            (
                deployment_namespace,
                consumer_role,
                rejection_id,
                rejection_id,
                selected_at,
                selected_at,
            ),
        ).fetchone()
        if row is None:
            return None
        now = _now(connection)
        if not (
            (row["status"] == "pending" and row["available_at"] <= now)
            or (
                row["status"] == "publishing"
                and row["lease_expires_at"] is not None
                and row["lease_expires_at"] <= now
            )
        ):
            return None
        diagnostic = BrokerDiagnostic(
            message_type="broker.delivery.rejected",
            schema_version=1,
            rejection_id=str(row["rejection_id"]),
            deployment_namespace=deployment_namespace,
            consumer_role=consumer_role,
            body_digest=row["body_digest"],
            byte_count=row["byte_count"],
            error_code=row["error_code"],
            created_at_ms=row["created_at_ms"],
        )
        connection.execute(
            """UPDATE command_delivery_rejections SET status='publishing', relay_owner=%s,
               relay_fence=relay_fence+1, lease_expires_at=%s, publish_attempts=publish_attempts+1
               WHERE deployment_namespace=%s AND rejection_id=%s""",
            (owner, _now(connection) + ttl, deployment_namespace, row["rejection_id"]),
        )
        return RejectionClaim(
            deployment_namespace,
            consumer_role,
            row["rejection_id"],
            owner,
            row["relay_fence"] + 1,
            diagnostic.model_dump_json().encode(),
        )


def settle_rejection(dsn: str, claim: RejectionClaim, *, confirmed: bool) -> bool:
    if not isinstance(claim, RejectionClaim) or type(confirmed) is not bool:
        raise ValueError("invalid rejection settlement")
    _owner(claim.owner)
    validate_rejection_metadata(claim.consumer_role, "invalid_broker_envelope")
    if not isinstance(claim.rejection_id, UUID) or type(claim.fence) is not int or claim.fence < 1:
        raise ValueError("invalid rejection claim fence")
    with _database(dsn, claim.deployment_namespace).connect() as connection:
        connection.execute("SET LOCAL lock_timeout='5s'")
        row = connection.execute(
            """SELECT * FROM command_delivery_rejections WHERE deployment_namespace=%s
               AND consumer_role=%s AND rejection_id=%s FOR UPDATE""",
            (claim.deployment_namespace, claim.consumer_role, claim.rejection_id),
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
        delay = timedelta(seconds=min(30, 2 ** min(row["publish_attempts"] - 1, 5)))
        connection.execute(
            """UPDATE command_delivery_rejections SET status=%s, published_at=%s,
               available_at=%s, relay_owner=NULL, lease_expires_at=NULL
               WHERE deployment_namespace=%s AND rejection_id=%s""",
            (
                "published" if confirmed else "pending",
                now if confirmed else None,
                now if confirmed else now + delay,
                claim.deployment_namespace,
                claim.rejection_id,
            ),
        )
        return True
