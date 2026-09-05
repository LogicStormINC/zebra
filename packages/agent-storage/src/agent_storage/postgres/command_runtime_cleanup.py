"""Fenced cleanup claims and exact post-engine settlements; no engine IO here."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from agent_core.domain.identifiers import SessionId

from agent_storage.postgres.command_runtime_cleanup_proof import cleanup_proof
from agent_storage.postgres.command_wakeup_discovery import _database
from agent_storage.postgres.command_wakeup_relay import _now, _owner, _ttl
from agent_storage.postgres.leases import lock_session_lease_boundary


@dataclass(frozen=True)
class CleanupTarget:
    instance_id: UUID
    container_id: str | None
    container_name: str
    labels: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CleanupClaim:
    namespace: str
    accepted_event_id: UUID | None
    session_id: UUID
    owner: str
    fence: int
    engine_identity: str
    target: CleanupTarget | None
    leased: bool = True
    cleanup_id: UUID | None = None
    direct_operation_id: UUID | None = None


def claim_runtime_cleanup(
    dsn: str,
    *,
    deployment_namespace: str,
    owner: str,
    engine_identity: str,
    ttl: timedelta = timedelta(seconds=60),
) -> CleanupClaim | None:
    """Claim one due obligation and at most one exact instance; invalid rows advance."""
    _owner(owner)
    _ttl(ttl)
    if len(engine_identity) != 64 or any(c not in "0123456789abcdef" for c in engine_identity):
        raise ValueError("invalid cleanup engine identity")
    namespace = deployment_namespace
    with _database(dsn, namespace).connect() as connection:
        connection.execute("SET LOCAL lock_timeout='5s'")
        selected_at = _now(connection)
        candidate = connection.execute(
            """SELECT * FROM command_runtime_cleanup WHERE deployment_namespace=%s AND
               ((status='pending' AND available_at<=%s) OR
                (status='cleaning' AND lease_expires_at<=%s AND available_at<=%s))
               ORDER BY available_at,cleanup_id LIMIT 1""",
            (namespace, selected_at, selected_at, selected_at),
        ).fetchone()
        if candidate is None:
            return None
        acquired = connection.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS acquired",
            (f"{namespace}:{candidate['session_id']}",),
        ).fetchone()
        assert acquired is not None
        if not acquired["acquired"]:
            # Scheduling metadata only. Never acquire a Session lock after taking
            # this row lock; commit deferral before trying another candidate.
            connection.execute(
                """UPDATE command_runtime_cleanup SET available_at=%s WHERE
                   (deployment_namespace,cleanup_id) IN
                   (SELECT deployment_namespace,cleanup_id FROM command_runtime_cleanup
                    WHERE deployment_namespace=%s AND cleanup_id=%s
                    FOR UPDATE SKIP LOCKED)""",
                (selected_at + timedelta(seconds=30), namespace, candidate["cleanup_id"]),
            )
            return CleanupClaim(
                namespace,
                candidate["accepted_event_id"],
                candidate["session_id"],
                owner,
                candidate["claim_fence"],
                engine_identity,
                None,
                False,
                candidate["cleanup_id"],
                candidate["direct_operation_id"],
            )
        _lock_stream(connection, namespace, candidate["session_id"])
        row = connection.execute(
            """SELECT * FROM command_runtime_cleanup WHERE deployment_namespace=%s
               AND cleanup_id=%s FOR UPDATE SKIP LOCKED""",
            (namespace, candidate["cleanup_id"]),
        ).fetchone()
        now = _now(connection)
        if row is None or not (
            (row["status"] == "pending" and row["available_at"] <= now)
            or (
                row["status"] == "cleaning"
                and row["lease_expires_at"] <= now
                and row["available_at"] <= now
            )
        ):
            return None
        if row["session_id"] != candidate["session_id"]:
            raise ValueError("cleanup identity changed during claim")
        try:
            if row["attempts"] >= 32 or now - row["created_at"] >= timedelta(days=1):
                raise ValueError("retry_budget_exhausted")
            proof = cleanup_proof(connection, namespace, row)
            instance = _next_instance(connection, namespace, proof)
            target = None if instance is None else _target(instance, proof)
        except ValueError as error:
            code = (
                "missing_revoked_fence"
                if str(error) == "missing_revoked_fence"
                else "retry_budget_exhausted"
                if str(error) == "retry_budget_exhausted"
                else "invalid_control_evidence"
            )
            connection.execute(
                """UPDATE command_runtime_cleanup SET status='requires_reconciliation',error_code=%s
                   WHERE deployment_namespace=%s AND cleanup_id=%s""",
                (code, namespace, row["cleanup_id"]),
            )
            return CleanupClaim(
                namespace,
                row["accepted_event_id"],
                row["session_id"],
                owner,
                row["claim_fence"],
                engine_identity,
                None,
                False,
                candidate["cleanup_id"],
                candidate["direct_operation_id"],
            )
        if instance is not None and instance["engine_identity"] != engine_identity:
            connection.execute(
                """UPDATE command_runtime_cleanup SET status='pending',
                   error_code='engine_unavailable',
                   available_at=%s,attempts=attempts+1
                   WHERE deployment_namespace=%s AND cleanup_id=%s""",
                (now + timedelta(seconds=30), namespace, row["cleanup_id"]),
            )
            return CleanupClaim(
                namespace,
                row["accepted_event_id"],
                row["session_id"],
                owner,
                row["claim_fence"],
                engine_identity,
                None,
                False,
                candidate["cleanup_id"],
                candidate["direct_operation_id"],
            )
        claimed = connection.execute(
            """UPDATE command_runtime_cleanup SET status='cleaning',claim_owner=%s,
               claim_fence=claim_fence+1,lease_expires_at=%s,attempts=attempts+1,error_code=NULL
               WHERE deployment_namespace=%s AND cleanup_id=%s RETURNING claim_fence""",
            (owner, now + ttl, namespace, row["cleanup_id"]),
        ).fetchone()
        assert claimed is not None
        return CleanupClaim(
            namespace,
            row["accepted_event_id"],
            row["session_id"],
            owner,
            claimed["claim_fence"],
            engine_identity,
            target,
            cleanup_id=row["cleanup_id"],
            direct_operation_id=row["direct_operation_id"],
        )


def settle_runtime_cleanup(
    dsn: str,
    claim: CleanupClaim,
    *,
    removed_container_id: str | None = None,
    error_code: str | None = None,
) -> bool:
    """Settle only exact successful observations under the unexpired cleanup fence."""
    if error_code not in (
        None,
        "engine_unavailable",
        "instance_identity_conflict",
        "creation_unsettled",
    ):
        raise ValueError("invalid cleanup result")
    namespace = claim.namespace
    with _database(dsn, namespace).connect() as connection:
        connection.execute("SET LOCAL lock_timeout='5s'")
        lock_session_lease_boundary(connection, namespace, SessionId(claim.session_id))
        _lock_stream(connection, namespace, claim.session_id)
        row = connection.execute(
            """SELECT * FROM command_runtime_cleanup WHERE deployment_namespace=%s
               AND cleanup_id=%s FOR UPDATE""",
            (namespace, claim.cleanup_id),
        ).fetchone()
        if not _current(row, claim, _now(connection)):
            return False
        assert row is not None
        proof = cleanup_proof(connection, namespace, row)
        if claim.target is not None:
            instance = connection.execute(
                """SELECT * FROM runtime_instances WHERE deployment_namespace=%s AND instance_id=%s
                   FOR UPDATE""",
                (namespace, claim.target.instance_id),
            ).fetchone()
            if (
                instance is None
                or (observed := _target(instance, proof)).labels != claim.target.labels
                or observed.container_name != claim.target.container_name
                or (
                    observed.container_id != claim.target.container_id
                    and not (
                        claim.target.container_id is None
                        and (
                            error_code is not None or observed.container_id == removed_container_id
                        )
                    )
                )
                or instance["engine_identity"] != claim.engine_identity
            ):
                raise ValueError("cleanup target changed after claim")
            if not _current(row, claim, _now(connection)):
                return False
            if error_code is None:
                if (
                    removed_container_id is None
                    or len(removed_container_id) != 64
                    or any(c not in "0123456789abcdef" for c in removed_container_id)
                    or claim.target.container_id not in (None, removed_container_id)
                ):
                    raise ValueError("cleanup requires an exact observed container identity")
                connection.execute(
                    """UPDATE runtime_instances SET container_id=%s,status='removed',
                       removed_at=clock_timestamp()
                       WHERE deployment_namespace=%s AND instance_id=%s""",
                    (removed_container_id, namespace, claim.target.instance_id),
                )
        remaining = _next_instance(connection, namespace, proof)
        done = error_code is None and remaining is None
        now = _now(connection)
        connection.execute(
            """UPDATE command_runtime_cleanup SET status=%s,error_code=%s,available_at=%s,
               attempts=CASE WHEN %s THEN 0 ELSE attempts END,
               claim_owner=NULL,lease_expires_at=NULL
               WHERE deployment_namespace=%s AND cleanup_id=%s""",
            (
                "done" if done else "pending",
                error_code,
                now + timedelta(seconds=min(30, 2 ** min(row["attempts"], 5))),
                error_code is None,
                namespace,
                claim.cleanup_id,
            ),
        )
        return True


def _current(row: Any, claim: CleanupClaim, now: Any) -> bool:
    return bool(
        row is not None
        and row["cleanup_id"] == claim.cleanup_id
        and row["accepted_event_id"] == claim.accepted_event_id
        and row["direct_operation_id"] == claim.direct_operation_id
        and row["status"] == "cleaning"
        and row["session_id"] == claim.session_id
        and row["claim_owner"] == claim.owner
        and row["claim_fence"] == claim.fence
        and row["lease_expires_at"] > now
    )


def _lock_stream(connection: Any, namespace: str, session_id: UUID) -> None:
    connection.execute(
        """SELECT current_version FROM session_streams WHERE deployment_namespace=%s
           AND session_id=%s FOR SHARE""",
        (namespace, session_id),
    ).fetchone()


def _next_instance(connection: Any, namespace: str, proof: dict[str, Any]) -> Any:
    return connection.execute(
        """SELECT * FROM runtime_instances WHERE deployment_namespace=%s AND session_id=%s
           AND control_plane_epoch=%s AND fencing_token=%s AND owner_instance_id=%s
           AND status<>'removed' ORDER BY created_at,instance_id LIMIT 1""",
        (
            namespace,
            proof["session_id"],
            proof["revoked_epoch"],
            proof["revoked_token"],
            proof["revoked_owner"],
        ),
    ).fetchone()


def _target(row: Any, proof: dict[str, Any]) -> CleanupTarget:
    if row["container_id"] is not None and (
        len(row["container_id"]) != 64
        or any(c not in "0123456789abcdef" for c in row["container_id"])
    ):
        raise ValueError("invalid_control_evidence")
    if (
        row["tenant_id"],
        row["workspace_id"],
        row["authority_issuer"],
        row["session_id"],
        row["control_plane_epoch"],
        row["fencing_token"],
        row["owner_instance_id"],
    ) != (
        proof["tenant_id"],
        proof["workspace_id"],
        proof["authority_issuer"],
        proof["session_id"],
        proof["revoked_epoch"],
        proof["revoked_token"],
        proof["revoked_owner"],
    ):
        raise ValueError("invalid_control_evidence")
    if row["container_name"] != f"zebra-{row['instance_id']}":
        raise ValueError("invalid_control_evidence")
    labels = {
        "zebra.agent.runtime": "1",
        "zebra.agent.instance": str(row["instance_id"]),
        "zebra.agent.namespace": row["deployment_namespace"],
        "zebra.agent.scope": row["scope_key"],
        "zebra.agent.session": str(row["session_id"]),
        "zebra.agent.spec": row["spec_digest"],
        "zebra.agent.engine": row["engine_identity"],
        "zebra.agent.epoch": str(row["control_plane_epoch"]),
        "zebra.agent.fence": str(row["fencing_token"]),
    }
    return CleanupTarget(
        row["instance_id"],
        row["container_id"],
        row["container_name"],
        tuple(sorted(labels.items())),
    )
