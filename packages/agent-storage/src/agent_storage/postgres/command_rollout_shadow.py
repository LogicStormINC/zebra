"""Default-off scope rollout and side-effect-free command shadow evidence."""

import json
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from agent_core.contracts.broker_envelope import ZebraCommandEnvelope, parse_broker_envelope

from agent_storage.postgres.command_rollout import command_scope_mode, rollout_text
from agent_storage.postgres.command_wakeup import command_scope_key
from agent_storage.postgres.command_wakeup_discovery import _database

SHADOW_ROLE = "command-shadow-v1"
MAX_SHADOW_BATCH = 32


@dataclass(frozen=True)
class ShadowClaim:
    deployment_namespace: str
    shadow_message_id: UUID
    source_message_id: UUID
    owner: str
    fence: int
    body: bytes


def record_command_shadow(
    connection: Any,
    *,
    deployment_namespace: str,
    source_message_id: UUID,
    scope_key: str,
    envelope_digest: str,
) -> UUID | None:
    """Mirror only protocol identity; capacity loss never blocks formal admission."""
    shadow_id = uuid5(NAMESPACE_URL, f"zebra-shadow:{deployment_namespace}:{source_message_id}")
    scope_lock = connection.execute(
        "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,50)) AS acquired",
        (f"{deployment_namespace}:command-rollout:{scope_key}",),
    ).fetchone()
    if scope_lock is None or not scope_lock["acquired"]:
        return None
    acquired = connection.execute(
        "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,50)) AS acquired",
        (f"{deployment_namespace}:command-shadow",),
    ).fetchone()
    if acquired is None or not acquired["acquired"]:
        return None
    if command_scope_mode(connection, deployment_namespace, scope_key) != "shadow":
        return None
    existing = connection.execute(
        """SELECT shadow_message_id,envelope_digest FROM command_shadow_outbox
           WHERE deployment_namespace=%s AND source_message_id=%s""",
        (deployment_namespace, source_message_id),
    ).fetchone()
    if existing is not None:
        if (existing["shadow_message_id"], existing["envelope_digest"]) != (
            shadow_id,
            envelope_digest,
        ):
            raise ValueError("command shadow identity conflict")
        return shadow_id
    rollout = connection.execute(
        """SELECT max_unpublished_shadow FROM command_wakeup_rollouts
           WHERE deployment_namespace=%s""",
        (deployment_namespace,),
    ).fetchone()
    if rollout is None:
        return None
    total = connection.execute(
        """SELECT count(*) AS value FROM command_shadow_outbox
           WHERE deployment_namespace=%s AND status IN ('pending','publishing')""",
        (deployment_namespace,),
    ).fetchone()["value"]
    if total >= rollout["max_unpublished_shadow"]:
        return None
    connection.execute(
        """INSERT INTO command_shadow_outbox
           (deployment_namespace,shadow_message_id,source_message_id,scope_key,envelope_digest)
           VALUES (%s,%s,%s,%s,%s)""",
        (deployment_namespace, shadow_id, source_message_id, scope_key, envelope_digest),
    )
    return shadow_id


def _body(row: dict[str, Any]) -> bytes:
    body = json.dumps(
        row["envelope_json"], sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    if sha256(body).hexdigest() != row["envelope_digest"]:
        raise ValueError("invalid shadow source digest")
    return body


def _mark_dead(connection: Any, namespace: str, shadow_message_id: UUID) -> None:
    connection.execute(
        """UPDATE command_shadow_outbox SET status='dead',relay_owner=NULL,
           lease_expires_at=NULL WHERE deployment_namespace=%s AND shadow_message_id=%s""",
        (namespace, shadow_message_id),
    )


def claim_command_shadow_batch(
    dsn: str,
    *,
    deployment_namespace: str,
    owner: str,
    batch_size: int = 16,
    ttl: timedelta = timedelta(seconds=30),
) -> tuple[ShadowClaim, ...]:
    owner = rollout_text(owner, maximum=128)
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_SHADOW_BATCH:
        raise ValueError("invalid shadow batch size")
    if not isinstance(ttl, timedelta) or not timedelta(0) < ttl <= timedelta(minutes=5):
        raise ValueError("invalid shadow claim ttl")
    claims = []
    with _database(dsn, deployment_namespace).connect() as connection:
        clock = connection.execute("SELECT clock_timestamp() AS value").fetchone()
        assert clock is not None
        now = clock["value"]
        rows = connection.execute(
            """SELECT shadow.*,source.envelope_json FROM command_shadow_outbox shadow
               JOIN broker_outbox source
                 ON source.deployment_namespace=shadow.deployment_namespace
                AND source.message_id=shadow.source_message_id
               WHERE shadow.deployment_namespace=%s AND
               ((shadow.status='pending' AND shadow.available_at<=%s) OR
                (shadow.status='publishing' AND shadow.lease_expires_at<=%s))
               ORDER BY shadow.available_at,shadow.shadow_message_id
               LIMIT %s FOR UPDATE OF shadow SKIP LOCKED""",
            (deployment_namespace, now, now, batch_size),
        ).fetchall()
        for row in rows:
            try:
                body = _body(row)
            except ValueError:
                _mark_dead(connection, deployment_namespace, row["shadow_message_id"])
                continue
            expires = now + ttl
            updated = connection.execute(
                """UPDATE command_shadow_outbox SET status='publishing',relay_owner=%s,
                   relay_fence=relay_fence+1,lease_expires_at=%s,
                   publish_attempts=publish_attempts+1
                   WHERE deployment_namespace=%s AND shadow_message_id=%s
                   RETURNING relay_fence""",
                (owner, expires, deployment_namespace, row["shadow_message_id"]),
            ).fetchone()
            assert updated is not None
            claims.append(
                ShadowClaim(
                    deployment_namespace,
                    row["shadow_message_id"],
                    row["source_message_id"],
                    owner,
                    updated["relay_fence"],
                    body,
                )
            )
    return tuple(claims)


def settle_command_shadow(dsn: str, claim: ShadowClaim, *, confirmed: bool) -> bool:
    if not isinstance(claim, ShadowClaim) or type(confirmed) is not bool:
        raise ValueError("invalid shadow settlement")
    with _database(dsn, claim.deployment_namespace).connect() as connection:
        clock = connection.execute("SELECT clock_timestamp() AS value").fetchone()
        assert clock is not None
        now = clock["value"]
        row = connection.execute(
            """SELECT * FROM command_shadow_outbox
               WHERE deployment_namespace=%s AND shadow_message_id=%s FOR UPDATE""",
            (claim.deployment_namespace, claim.shadow_message_id),
        ).fetchone()
        if (
            row is None
            or row["status"] != "publishing"
            or row["relay_owner"] != claim.owner
            or row["relay_fence"] != claim.fence
            or row["lease_expires_at"] is None
            or row["lease_expires_at"] <= now
            or row["source_message_id"] != claim.source_message_id
            or row["envelope_digest"] != sha256(claim.body).hexdigest()
        ):
            return False
        connection.execute(
            """UPDATE command_shadow_outbox SET status=%s,published_at=%s,
               available_at=%s,relay_owner=NULL,lease_expires_at=NULL
               WHERE deployment_namespace=%s AND shadow_message_id=%s""",
            (
                "published" if confirmed else "pending",
                now if confirmed else None,
                row["available_at"] if confirmed else now + timedelta(seconds=1),
                claim.deployment_namespace,
                claim.shadow_message_id,
            ),
        )
        return True


def observe_command_shadow(dsn: str, *, deployment_namespace: str, body: bytes) -> bool:
    """Record protocol observation only; no formal Inbox, lease or business write."""
    if not isinstance(body, bytes) or len(body) > 16384:
        raise ValueError("invalid shadow envelope")
    try:
        envelope = parse_broker_envelope(body)
        if not isinstance(envelope, ZebraCommandEnvelope):
            raise ValueError
        if envelope.deployment_namespace != deployment_namespace:
            raise ValueError
        source_id = UUID(envelope.message_id)
        scope_key = command_scope_key(envelope.scope)
        digest = sha256(body).hexdigest()
    except (ValueError, TypeError, KeyError):
        raise ValueError("invalid shadow envelope") from None
    with _database(dsn, deployment_namespace).connect() as connection:
        source = connection.execute(
            """SELECT shadow.shadow_message_id,source.scope_key,source.envelope_digest
               FROM command_shadow_outbox shadow JOIN broker_outbox source
                 ON source.deployment_namespace=shadow.deployment_namespace
                AND source.message_id=shadow.source_message_id
               WHERE shadow.deployment_namespace=%s AND shadow.source_message_id=%s""",
            (deployment_namespace, source_id),
        ).fetchone()
        if source is None or (source["scope_key"], source["envelope_digest"]) != (
            scope_key,
            digest,
        ):
            raise ValueError("shadow source reconciliation failed")
        shadow_id = source["shadow_message_id"]
        inserted = connection.execute(
            """INSERT INTO command_shadow_observations
               (deployment_namespace,consumer_role,shadow_message_id,source_message_id,
                scope_key,envelope_digest) VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT DO NOTHING RETURNING shadow_message_id""",
            (deployment_namespace, SHADOW_ROLE, shadow_id, source_id, scope_key, digest),
        ).fetchone()
        return inserted is not None


def reject_command_shadow(dsn: str, *, deployment_namespace: str, body: bytes) -> bool:
    """Persist only a bounded digest before ACKing an invalid shadow delivery."""
    if not isinstance(body, bytes) or len(body) > 1_048_576:
        raise ValueError("invalid shadow rejection body")
    digest = sha256(body).hexdigest()
    with _database(dsn, deployment_namespace).connect() as connection:
        inserted = connection.execute(
            """INSERT INTO command_shadow_rejections
               (deployment_namespace,consumer_role,body_digest,rejection_code)
               VALUES (%s,%s,%s,'invalid_shadow_envelope')
               ON CONFLICT DO NOTHING RETURNING body_digest""",
            (deployment_namespace, SHADOW_ROLE, digest),
        ).fetchone()
        return inserted is not None


def command_shadow_reconciliation(dsn: str, *, deployment_namespace: str) -> dict[str, int]:
    with _database(dsn, deployment_namespace).connect() as connection:
        row = connection.execute(
            """SELECT count(DISTINCT formal.message_id) AS eligible,
               count(DISTINCT shadow.shadow_message_id) AS mirrored,
               count(DISTINCT shadow.shadow_message_id)
                 FILTER (WHERE shadow.status='published') AS published,
               count(DISTINCT observation.shadow_message_id) AS observed
               FROM broker_outbox formal
               JOIN command_delivery_scope_rollouts rollout
                 ON rollout.deployment_namespace=formal.deployment_namespace
                AND rollout.scope_key=formal.scope_key AND rollout.mode='shadow'
               LEFT JOIN command_shadow_outbox shadow
                 ON shadow.deployment_namespace=formal.deployment_namespace
                AND shadow.source_message_id=formal.message_id
                AND shadow.scope_key=formal.scope_key
                AND shadow.envelope_digest=formal.envelope_digest
               LEFT JOIN command_shadow_observations observation
                 ON observation.deployment_namespace=formal.deployment_namespace
                AND observation.shadow_message_id=shadow.shadow_message_id
                AND observation.source_message_id=formal.message_id
                AND observation.scope_key=formal.scope_key
                AND observation.envelope_digest=formal.envelope_digest
               WHERE formal.deployment_namespace=%s""",
            (deployment_namespace,),
        ).fetchone()
    assert row is not None
    return {
        "eligible": row["eligible"],
        "mirrored": row["mirrored"],
        "published": row["published"],
        "observed": row["observed"],
    }
