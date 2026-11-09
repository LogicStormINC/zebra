"""Fresh fenced canonical frontier transactions; no network or borrowed ownership."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from agent_core.domain.identifiers import SessionId

from agent_storage.postgres.command_wakeup_relay import _now, _owner, _ttl
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.work_unit import borrow_work_unit


@dataclass(frozen=True, slots=True)
class StreamHintClaim:
    namespace: str
    session_id: SessionId
    owner: str
    fence: int
    through: int
    expires_at: datetime


def _database(dsn: str, namespace: str) -> PostgresDatabase:
    database = PostgresDatabase(dsn, deployment_namespace=namespace)
    if borrow_work_unit((dsn, namespace)) is not None:
        raise RuntimeError("stream hint relay cannot borrow caller transaction")
    return database


def claim_stream_hints(
    dsn: str,
    *,
    namespace: str,
    owner: str,
    limit: int = 32,
    ttl: timedelta = timedelta(seconds=30),
) -> tuple[StreamHintClaim, ...]:
    _owner(owner)
    _ttl(ttl)
    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError("stream hint batch must be between 1 and 32")
    claims: list[StreamHintClaim] = []
    with _database(dsn, namespace).connect_task_io() as connection:
        # TaskIO's native connection is always fresh; default READ COMMITTED.
        selected_at = _now(connection)
        for claimed, due in ((False, "next_attempt_at"), (True, "lease_expires_at")):
            if len(claims) == limit:
                break
            # ponytail: cap32 in the canonical table; split hint storage only if
            # these short set-based transactions still contend with Event appends.
            owner_check = "IS NOT NULL" if claimed else "IS NULL"
            rows = connection.execute(
                f"""WITH picked AS MATERIALIZED (
                    SELECT session_id,{due} AS due_at FROM session_streams
                    WHERE deployment_namespace=%s AND current_version>published_through
                      AND claim_owner {owner_check} AND {due}<=%s
                    ORDER BY {due},session_id LIMIT %s FOR UPDATE SKIP LOCKED
                ), updated AS (
                    UPDATE session_streams AS stream SET claim_owner=%s,
                      claim_fence=stream.claim_fence+1, claimed_through=stream.current_version,
                      lease_expires_at=clock_timestamp()+%s
                    FROM picked WHERE stream.deployment_namespace=%s
                      AND stream.session_id=picked.session_id
                    RETURNING stream.session_id,stream.claim_fence,stream.claimed_through,
                      stream.lease_expires_at,picked.due_at
                ) SELECT session_id,claim_fence,claimed_through,lease_expires_at FROM updated
                  ORDER BY due_at,session_id""",
                (namespace, selected_at, limit - len(claims), owner, ttl, namespace),
            ).fetchall()
            claims.extend(
                StreamHintClaim(
                    namespace,
                    SessionId(row["session_id"]),
                    owner,
                    row["claim_fence"],
                    row["claimed_through"],
                    row["lease_expires_at"],
                )
                for row in rows
            )
    return tuple(claims)  # Commit and connection close precede caller publication.


def settle_stream_hint(dsn: str, claim: StreamHintClaim, *, confirmed: bool) -> bool:
    if not isinstance(claim, StreamHintClaim) or type(confirmed) is not bool:
        raise ValueError("invalid stream hint settlement")
    _owner(claim.owner)
    if not isinstance(claim.session_id, UUID) or type(claim.fence) is not int or claim.fence < 1:
        raise ValueError("invalid stream hint identity")
    if type(claim.through) is not int or claim.through < 0:
        raise ValueError("invalid stream hint frontier")
    with _database(dsn, claim.namespace).connect_task_io() as connection:
        row = connection.execute(
            """SELECT claim_owner,claim_fence,claimed_through,lease_expires_at
            FROM session_streams WHERE deployment_namespace=%s AND session_id=%s
            FOR UPDATE SKIP LOCKED""",
            (claim.namespace, claim.session_id),
        ).fetchone()
        # A busy durable writer wins; this hint remains reclaimable at expiry.
        if row is None:
            return False
        now = _now(connection)
        if (
            row["claim_owner"] != claim.owner
            or row["claim_fence"] != claim.fence
            or row["claimed_through"] != claim.through
            or row["lease_expires_at"] != claim.expires_at
            or row["lease_expires_at"] <= now
        ):
            return False
        connection.execute(
            """UPDATE session_streams SET published_through=CASE WHEN %s THEN
            GREATEST(published_through,%s) ELSE published_through END,
            claim_owner=NULL,claimed_through=NULL,lease_expires_at=NULL,next_attempt_at=%s
            WHERE deployment_namespace=%s AND session_id=%s""",
            (
                confirmed,
                claim.through,
                now if confirmed else now + timedelta(seconds=1),
                claim.namespace,
                claim.session_id,
            ),
        )
        return True
