"""Explicit bounded storage recovery; never recover an uncertain executing program."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from agent_core.contracts.broker_envelope import PrincipalScope
from agent_core.contracts.session_commands import SessionCommandKind
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from psycopg.errors import LockNotAvailable, QueryCanceled
from psycopg.types.json import Jsonb

from agent_storage.postgres.command_wakeup import (
    _check_outbox_capacity,
    _envelope,
    command_scope_key,
    insert_command_outbox,
)
from agent_storage.postgres.command_wakeup_discovery import _database
from agent_storage.postgres.command_wakeup_handoff import _terminal_session, _validate
from agent_storage.postgres.command_wakeup_recovery_proof import (
    MAX_GENERATION as MAX_GENERATION,
)
from agent_storage.postgres.command_wakeup_recovery_proof import (
    MAX_TOTAL_AGE as MAX_TOTAL_AGE,
)
from agent_storage.postgres.command_wakeup_recovery_proof import (
    CoverageRecoveryCheck,
    check_coverage_recovery_clock,
    coverage_generation_usage,
    coverage_progress,
    verified_coverage_recovery,
)
from agent_storage.postgres.coverage_recovery_preparation import (
    CoverageRecoveryDeferred,
    check_prepared_recovery_clock,
    prepare_command_recovery,
    prepared_recovery_connection,
)
from agent_storage.postgres.leases import (
    _active,
    _lock_epoch,
    _lock_lease_and_clock,
    assert_current_lease_fence,
    lock_session_lease_boundary,
)

RETRY_DELAY = timedelta(seconds=60)


class RecoveryStatus(StrEnum):
    APPROVED = "approved"
    DEFERRED = "deferred"
    REQUIRES_RECONCILIATION = "requires_reconciliation"
    EXHAUSTED = "exhausted"
    IGNORED = "ignored"


@dataclass(frozen=True)
class CommandRecovery:
    accepted_event_id: UUID
    generation: int
    status: RecoveryStatus


def recover_command_batch(
    dsn: str,
    *,
    deployment_namespace: str,
    scope: PrincipalScope,
    batch_size: int = 16,
    coverage_check: CoverageRecoveryCheck | None = None,
) -> tuple[CommandRecovery, ...]:
    """Opt-in operator invocation; each candidate is one short, independently atomic TX.

    ponytail: every post-floor Event is quarantined, even harmless title changes.
    This trades availability for proof; later reconciliation can classify evidence.
    No background activation, model rerun, or business retry budget is introduced.
    """
    if (
        not isinstance(scope, PrincipalScope)
        or type(batch_size) is not int
        or not 1 <= batch_size <= 100
    ):
        raise ValueError("recovery requires trusted scope and an integer batch size from 1 to 100")
    database = _database(dsn, deployment_namespace)
    with database.connect() as connection:
        clock = connection.execute("SELECT clock_timestamp() AS now").fetchone()
        assert clock is not None
        now = clock["now"]
        rows = connection.execute(
            """SELECT accepted_event_id, session_id FROM session_command_pending
               WHERE deployment_namespace = %s AND scope_key = %s AND status = 'pending'
                 AND tenant_id = %s AND workspace_id = %s
                 AND origin = 'live' AND recovery_due_at <= %s
               ORDER BY recovery_due_at, accepted_event_id LIMIT %s""",
            (
                deployment_namespace,
                command_scope_key(scope),
                scope.tenant_id,
                scope.workspace_id,
                now,
                batch_size,
            ),
        ).fetchall()
    results = []
    for row in rows:
        try:
            with database.connect() as connection:
                connection.execute("SET LOCAL lock_timeout = '5s'")
                results.append(
                    _recover(
                        connection, deployment_namespace, scope, row, coverage_check=coverage_check
                    )
                )
        except (CoverageRecoveryDeferred, QueryCanceled, LockNotAvailable):
            results.append(CommandRecovery(row["accepted_event_id"], 0, RecoveryStatus.DEFERRED))
    return tuple(results)


def _recover(
    connection: Any,
    namespace: str,
    scope: PrincipalScope,
    candidate: dict[str, Any],
    *,
    coverage_check: CoverageRecoveryCheck | None = None,
    continuation_fence: LeaseFence | None = None,
) -> CommandRecovery:
    event_id = candidate["accepted_event_id"]
    session_id = SessionId(candidate["session_id"])
    if (
        continuation_fence is None
        and connection.execute(
            """SELECT 1 FROM worker_leases AS lease
           JOIN control_plane_epochs AS authority USING (deployment_namespace)
           WHERE lease.deployment_namespace=%s AND lease.session_id=%s
             AND lease.control_plane_epoch=authority.epoch
             AND lease.released_at IS NULL AND lease.expires_at>clock_timestamp()""",
            (namespace, session_id),
        ).fetchone()
        is not None
    ):
        # Read-only hint avoids a new lock acquisition/release round for inactive
        # leases. It cannot defer anything: the locked conditional UPDATE must agree.
        connection.execute("SAVEPOINT command_recovery_preflight")
        lock_session_lease_boundary(connection, namespace, session_id)
        _lock_epoch(connection, namespace)
        _lock_lease_and_clock(connection, namespace, session_id, update=True)
        # Denial only: a racing release may delay recovery by RETRY_DELAY, never
        # authorize execution. Move active candidates off the due page so they
        # cannot starve expired leases. Inactive/fenced paths retain full proof.
        deferred = connection.execute(
            """UPDATE session_command_pending AS pending
               SET recovery_due_at = clock_timestamp() + %s
               FROM worker_leases AS lease, control_plane_epochs AS authority,
                    command_wakeup_rollouts AS rollout
               WHERE pending.deployment_namespace = %s AND pending.accepted_event_id = %s
                 AND pending.session_id = %s AND pending.scope_key = %s
                 AND pending.tenant_id = %s AND pending.workspace_id = %s
                 AND pending.status = 'pending' AND pending.origin = 'live'
                 AND pending.recovery_due_at <= clock_timestamp()
                 AND lease.deployment_namespace = pending.deployment_namespace
                 AND lease.session_id = pending.session_id
                 AND authority.deployment_namespace = pending.deployment_namespace
                 AND lease.control_plane_epoch = authority.epoch
                 AND lease.released_at IS NULL AND lease.expires_at > clock_timestamp()
                 AND rollout.deployment_namespace = pending.deployment_namespace
                 AND rollout.admission_enabled
               RETURNING pending.current_generation""",
            (
                RETRY_DELAY,
                namespace,
                event_id,
                session_id,
                command_scope_key(scope),
                scope.tenant_id,
                scope.workspace_id,
            ),
        ).fetchone()
        if deferred is not None:
            connection.execute("RELEASE SAVEPOINT command_recovery_preflight")
            return CommandRecovery(
                event_id, deferred["current_generation"], RecoveryStatus.DEFERRED
            )
        # Release even locks taken before an UPDATE predicate recheck missed.
        # Never prepare external proof while holding these lifecycle locks.
        connection.execute("ROLLBACK TO SAVEPOINT command_recovery_preflight")
        connection.execute("RELEASE SAVEPOINT command_recovery_preflight")
    coverage_check = prepare_command_recovery(
        coverage_check, namespace, event_id, continuation=continuation_fence is not None,
    )
    connection = prepared_recovery_connection(connection, coverage_check)
    lock_session_lease_boundary(connection, namespace, session_id)
    epoch = _lock_epoch(connection, namespace)
    lease, now = _lock_lease_and_clock(connection, namespace, session_id, update=True)
    # Match worker ordering; also stop an unfenced MESSAGE/command insert racing
    # the proof and approval. No stream/business lock is taken before the lease.
    stream = connection.execute(
        """SELECT current_version FROM session_streams
           WHERE deployment_namespace = %s AND session_id = %s FOR UPDATE""",
        (namespace, session_id),
    ).fetchone()
    pending = connection.execute(
        """SELECT * FROM session_command_pending WHERE deployment_namespace = %s
           AND accepted_event_id = %s FOR UPDATE""",
        (namespace, event_id),
    ).fetchone()
    assert pending is not None
    now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"].astimezone(UTC)
    generation = pending["current_generation"]

    def result(status: RecoveryStatus) -> CommandRecovery:
        return CommandRecovery(event_id, generation, status)

    if (
        pending["scope_key"] != command_scope_key(scope)
        or pending["tenant_id"] != scope.tenant_id
        or pending["workspace_id"] != scope.workspace_id
        or pending["session_id"] != session_id
    ):
        raise ValueError("command recovery scope mismatch")
    if (
        pending["status"] != "pending"
        or pending["origin"] != "live"
        or (continuation_fence is None and pending["recovery_due_at"] > now)
    ):
        return result(RecoveryStatus.IGNORED)
    rollout = connection.execute(
        "SELECT admission_enabled FROM command_wakeup_rollouts "
        "WHERE deployment_namespace = %s FOR SHARE",
        (namespace,),
    ).fetchone()
    if rollout is None or not rollout["admission_enabled"]:
        return result(RecoveryStatus.IGNORED)
    if continuation_fence is not None:
        assert_current_lease_fence(connection, namespace, session_id, continuation_fence)
    elif lease is not None and _active(lease, epoch, now):
        _defer(connection, namespace, event_id, now + RETRY_DELAY)
        return result(RecoveryStatus.DEFERRED)
    outbox = connection.execute(
        """SELECT * FROM broker_outbox WHERE deployment_namespace = %s AND scope_key = %s
           AND operation_id = %s AND wake_generation = %s
           AND message_type = 'zebra.session.command.ready'""",
        (namespace, pending["scope_key"], pending["command_id"], generation),
    ).fetchone()
    if outbox is not None and outbox["status"] == "dead":
        _stop(connection, namespace, event_id, "terminal_or_dead")
        return result(RecoveryStatus.REQUIRES_RECONCILIATION)
    try:
        if outbox is None:
            raise ValueError("missing command recovery outbox")
        _validate(connection, namespace, pending, outbox, scope, None)
    except (ValueError, TypeError, KeyError):
        # Only validated caller-scope derived pending is quarantined. Database
        # errors propagate and roll back; never store exception/input text.
        _stop(connection, namespace, event_id, "invalid_outbox")
        return result(RecoveryStatus.REQUIRES_RECONCILIATION)
    receipt = connection.execute(
        """SELECT * FROM command_handoff_receipts WHERE deployment_namespace = %s
           AND accepted_event_id = %s FOR UPDATE""",
        (namespace, event_id),
    ).fetchone()
    if _terminal_session(connection, namespace, session_id):
        _stop(connection, namespace, event_id, "terminal_or_dead")
        return result(RecoveryStatus.REQUIRES_RECONCILIATION)
    if receipt is not None:
        if receipt["handled_event_id"] is not None or receipt["status"] != "accepted":
            _stop(connection, namespace, event_id, "requires_reconciliation")
            return result(RecoveryStatus.REQUIRES_RECONCILIATION)
        # After a generation approval, the prior receipt remains until the next
        # actual handoff; it is not evidence that this newer generation ran.
        if receipt["wake_generation"] != generation:
            receipt = None
    floor = pending["accepted_sequence"] if receipt is None else receipt["execution_floor_sequence"]
    uncertain = floor is None or (receipt is not None and receipt["started_event_id"] is not None)
    if receipt is not None:
        uncertain = (
            uncertain
            or lease is None
            or any(
                lease[field] != receipt[field]
                for field in ("control_plane_epoch", "fencing_token", "owner_instance_id")
            )
        )
        if (
            not uncertain
            and continuation_fence is None
            and lease is not None
            and lease["expires_at"] > now
        ):
            _defer(connection, namespace, event_id, now + RETRY_DELAY)
            return result(RecoveryStatus.DEFERRED)
    if not uncertain:
        uncertain = (
            connection.execute(
                """SELECT 1 FROM session_events WHERE deployment_namespace = %s
               AND session_id = %s AND sequence > %s LIMIT 1""",
                (namespace, session_id, floor),
            ).fetchone()
            is not None
        )
    coverage_proof = None
    if (uncertain or continuation_fence is not None) and coverage_check is not None:
        try:
            coverage_proof = verified_coverage_recovery(
                connection, namespace, pending, receipt, coverage_check
            )
        except (ValueError, TypeError, KeyError):
            pass  # No proof is ordinary uncertainty, never permission to rerun.
    if uncertain and coverage_proof is None:
        _stop(connection, namespace, event_id, "requires_reconciliation")
        return result(RecoveryStatus.REQUIRES_RECONCILIATION)
    fresh_proof = None
    from agent_storage.postgres.erp_fresh_disposition import (
        UNAVAILABLE, EXHAUSTED, verified_fresh_disposition,
    )
    if pending["recovery_code"] == UNAVAILABLE:
        try:
            fresh_proof = verified_fresh_disposition(connection, namespace, event_id)
            if fresh_proof is None or receipt is None or uncertain:
                raise ValueError("known unavailable command lost its unstarted proof")
        except (ValueError, TypeError, KeyError):
            _stop(connection, namespace, event_id, "requires_reconciliation")
            return result(RecoveryStatus.REQUIRES_RECONCILIATION)
    crashes = generation
    if coverage_proof is not None:
        try:
            crashes, previous_accepted = coverage_generation_usage(
                connection, namespace, pending, coverage_proof, maximum_crashes=MAX_GENERATION
            )
            expected, accepted = coverage_progress(coverage_proof)
            if continuation_fence is not None and not previous_accepted < accepted < expected:
                raise ValueError("strict continuation requires new accepted progress")
        except (ValueError, TypeError, KeyError):
            _stop(connection, namespace, event_id, "requires_reconciliation")
            return result(RecoveryStatus.REQUIRES_RECONCILIATION)
    elif continuation_fence is not None:
        raise ValueError("strict continuation requires its current native coverage proof")
    if (continuation_fence is None and crashes >= MAX_GENERATION) or now - pending[
        "created_at"
    ] >= MAX_TOTAL_AGE:
        _stop(connection, namespace, event_id, EXHAUSTED if fresh_proof is not None else "recovery_exhausted")
        return result(RecoveryStatus.EXHAUSTED)
    if receipt is None and (
        outbox["status"] != "published"
        or outbox["published_at"] is None
        or outbox["published_at"] + RETRY_DELAY > now
    ):
        _defer(connection, namespace, event_id, now + RETRY_DELAY)
        return result(RecoveryStatus.DEFERRED)
    event_row = connection.execute(
        """SELECT event_id, session_id, sequence, event_type, payload, actor, created_at,
                  causation_id, correlation_id, idempotency_key, policy_version, model_profile
           FROM session_events WHERE deployment_namespace = %s AND event_id = %s""",
        (namespace, event_id),
    ).fetchone()
    assert event_row is not None and stream is not None
    envelope = _envelope(
        namespace, SessionEvent.model_validate(event_row), scope, generation=generation + 1
    )
    capacity = connection.execute(
        """SELECT max_unpublished_outbox, reserved_control_outbox
           FROM command_wakeup_rollouts WHERE deployment_namespace=%s""",
        (namespace,),
    ).fetchone()
    assert capacity is not None
    _check_outbox_capacity(
        connection,
        namespace,
        SessionCommandKind(pending["command_kind"]),
        max_unpublished_outbox=capacity["max_unpublished_outbox"],
        reserved_control_outbox=capacity["reserved_control_outbox"],
    )
    insert_command_outbox(connection, envelope)
    connection.execute(
        """INSERT INTO command_recovery_attempts (deployment_namespace, accepted_event_id,
           wake_generation, previous_message_id, message_id, approved_stream_sequence,
           reason, previous_receipt, coverage_proof)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            namespace,
            event_id,
            generation + 1,
            outbox["message_id"],
            envelope.message_id,
            stream["current_version"],
            ("coverage_continuation" if continuation_fence is not None else "coverage_checkpoint")
            if coverage_proof is not None
            else ("published_no_handoff" if receipt is None else "expired_unstarted"),
            None if receipt is None else Jsonb({
                **_receipt_snapshot(receipt),
                **({"early_authority_code": UNAVAILABLE,
                    "early_authority_proof": f"{event_id}:{generation}"}
                   if fresh_proof is not None else {}),
            }),
            None if coverage_proof is None else Jsonb(coverage_proof),
        ),
    )
    connection.execute(
        """UPDATE session_command_pending SET current_generation = %s, recovery_due_at = %s,
           recovery_code = NULL WHERE deployment_namespace = %s AND accepted_event_id = %s""",
        (
            generation + 1,
            now + RETRY_DELAY * min(2 ** min(generation + 1, 4), 15),
            namespace,
            event_id,
        ),
    )
    if coverage_proof is not None:
        check_coverage_recovery_clock(connection, coverage_proof, pending=pending)
    if continuation_fence is not None:
        assert_current_lease_fence(connection, namespace, session_id, continuation_fence)
    if coverage_proof is not None:
        check_prepared_recovery_clock(
            connection, coverage_check, proof=coverage_proof, pending=pending
        )
    return CommandRecovery(event_id, generation + 1, RecoveryStatus.APPROVED)


def continue_coverage_command(
    connection: Any,
    namespace: str,
    session_id: SessionId,
    fence: LeaseFence,
    coverage_check: CoverageRecoveryCheck,
) -> CommandRecovery:
    """One native generation/outbox/proof transaction after a bounded batch.

    A crash between accepted results and this transition is handled by the same
    expired-lease proof. No synthetic completion, suspension or new Task input.
    """
    rows = connection.execute(
        """SELECT p.* FROM session_command_pending p JOIN command_handoff_receipts r
           ON r.deployment_namespace=p.deployment_namespace
             AND r.accepted_event_id=p.accepted_event_id
           WHERE p.deployment_namespace=%s AND p.session_id=%s AND p.status='pending'
             AND r.status='accepted' AND r.handled_event_id IS NULL
             AND r.control_plane_epoch=%s AND r.fencing_token=%s
             AND r.owner_instance_id=%s LIMIT 2""",
        (
            namespace,
            session_id,
            fence.control_plane_epoch,
            fence.fencing_token,
            fence.owner_instance_id,
        ),
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("bounded strict continuation requires one native command handoff")
    row = rows[0]
    scope = PrincipalScope(
        kind="principal", tenant_id=row["tenant_id"], workspace_id=row["workspace_id"]
    )
    result = _recover(
        connection,
        namespace,
        scope,
        row,
        coverage_check=coverage_check,
        continuation_fence=fence,
    )
    if result.status is not RecoveryStatus.APPROVED:
        raise ValueError("strict continuation has no current native recovery proof")
    return result


def _receipt_snapshot(receipt: dict[str, Any]) -> dict[str, Any]:
    # Explicit allowlist: never let future receipt columns leak into audit JSON.
    fields = (
        "scope_key",
        "command_id",
        "accepted_event_id",
        "session_id",
        "status",
        "control_plane_epoch",
        "fencing_token",
        "owner_instance_id",
        "created_at",
        "execution_floor_sequence",
        "started_event_id",
        "handled_event_id",
        "turn_id",
        "wake_generation",
    )
    return {
        field: (value if value is None or isinstance(value, str | int) else str(value))
        for field in fields
        for value in (receipt[field],)
    }


def _defer(connection: Any, namespace: str, event_id: UUID, due: datetime) -> None:
    connection.execute(
        """UPDATE session_command_pending SET recovery_due_at = %s
           WHERE deployment_namespace = %s AND accepted_event_id = %s""",
        (due, namespace, event_id),
    )


def _stop(connection: Any, namespace: str, event_id: UUID, code: str) -> None:
    connection.execute(
        """UPDATE session_command_pending SET status = 'dead', recovery_code = %s
           WHERE deployment_namespace = %s AND accepted_event_id = %s""",
        (code, namespace, event_id),
    )
