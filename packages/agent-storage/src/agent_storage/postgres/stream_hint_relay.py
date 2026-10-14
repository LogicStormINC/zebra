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
            rows = connection.execute(
                "SELECT session_id,current_version FROM session_streams "
                "WHERE deployment_namespace=%s AND current_version>published_through "
                + ("AND claim_owner IS NOT NULL " if claimed else "AND claim_owner IS NULL ")
                + f"AND {due}<=%s ORDER BY {due},session_id LIMIT %s FOR UPDATE SKIP LOCKED",
                (namespace, selected_at, limit - len(claims)),
            ).fetchall()
            for row in rows:
                now = _now(connection)  # Sample DB clock after owning the row lock.
                result = connection.execute(
                    """UPDATE session_streams SET claim_owner=%s,claim_fence=claim_fence+1,
                    lease_expires_at=%s,claimed_through=current_version
                    WHERE deployment_namespace=%s AND session_id=%s
                    RETURNING claim_fence,claimed_through""",
                    (owner, now + ttl, namespace, row["session_id"]),
                ).fetchone()
                assert result is not None
                claims.append(
                    StreamHintClaim(
                        namespace,
                        SessionId(row["session_id"]),
                        owner,
                        result["claim_fence"],
                        result["claimed_through"],
                        now + ttl,
                    )
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
            FROM session_streams WHERE deployment_namespace=%s AND session_id=%s FOR UPDATE""",
            (claim.namespace, claim.session_id),
        ).fetchone()
        now = _now(connection)
        if (
            row is None
            or row["claim_owner"] != claim.owner
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
