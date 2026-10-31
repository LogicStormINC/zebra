"""Atomic command-to-Lease handoff shared by broker and fallback; no execution."""

from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from agent_core.contracts.broker_envelope import PrincipalScope, ZebraCommandEnvelope
from agent_core.domain.identifiers import EventId, SessionId
from agent_core.domain.leases import DEFAULT_MAX_LEASE_TTL, LeaseConflictError
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_storage.postgres.command_coverage_admission import (
    pin_command_consumer,
    reject_missing_command_consumer,
)
from agent_storage.postgres.command_handoff_envelope import parse_handoff_envelope
from agent_storage.postgres.command_handoff_inbox import _check_inbox, _inbox
from agent_storage.postgres.command_handoff_policy import (
    check_handoff_policy,
    defer_handoff_scope,
    require_private_handoff_preparation,
    settle_private_handoff,
)
from agent_storage.postgres.command_handoff_types import (
    CommandHandoff,
    HandoffStatus,
    _TerminalAfterLease,
)
from agent_storage.postgres.command_read_budget import command_read_budget
from agent_storage.postgres.command_read_preflight import prepare_command_candidate
from agent_storage.postgres.command_rollout import command_scope_mode
from agent_storage.postgres.command_wakeup import command_scope_key
from agent_storage.postgres.command_wakeup_discovery import _database
from agent_storage.postgres.command_wakeup_message import (
    MessageInputRejected,
    append_command_message,
)
from agent_storage.postgres.command_wakeup_receipts import _terminal_session, _validate
from agent_storage.postgres.command_wakeup_recovery_proof import (
    MAX_GENERATION,
    CoverageRecoveryCheck,
    check_coverage_recovery_clock,
    coverage_generation_usage,
    recovery_approval,
    verified_coverage_recovery,
)
from agent_storage.postgres.coverage_recovery_preparation import (
    check_prepared_recovery_clock,
    prepare_command_handoff,
    prepared_recovery_connection,
)
from agent_storage.postgres.erp_workspace_policy import (
    containment_enabled,
    private_activation_enabled,
)
from agent_storage.postgres.events import read_event_in_transaction
from agent_storage.postgres.leases import (
    acquire_lease_in_transaction,
    assert_current_lease_fence,
    lock_session_lease_boundary,
)
from agent_storage.postgres.worker_capability import (
    WorkerCapabilityLease,
    WorkerCapabilityLostError,
    check_worker_capability_clock,
)


@command_read_budget
def handoff_command(
    dsn: str,
    *,
    deployment_namespace: str,
    scope: PrincipalScope,
    accepted_event_id: UUID,
    owner_instance_id: str,
    ttl: timedelta,
    raw_body: bytes | None = None,
    maximum_ttl: timedelta = DEFAULT_MAX_LEASE_TTL,
    required_scope_mode: Literal["broker", "fallback"] | None = None,
    coverage_check: CoverageRecoveryCheck | None = None,
    consumer_capability: WorkerCapabilityLease | None = None,
    private_preparation: Any = None,
) -> CommandHandoff:
    """Trusted scope is independent of the message; success is not scheduler ACK.

    Only a new ACCEPTED result carries execution authority. A duplicate never
    reacquires an expired lease. Historical ambiguity requires external accounting.
    MESSAGE input is atomic here; control commands use their dedicated path.
    """
    envelope = parse_handoff_envelope(
        raw_body, scope, deployment_namespace, accepted_event_id, required_scope_mode
    )
    contained = containment_enabled(deployment_namespace)
    private = private_activation_enabled(deployment_namespace)
    if not contained or private and callable(private_preparation):
        preparing = prepare_command_candidate(
            dsn,
            deployment_namespace,
            scope,
            accepted_event_id,
            raw_body,
            envelope.wake_generation if envelope is not None else None,
            required_scope_mode,
            message_only=True,
            private_preparation=private_preparation,
        )
        if preparing is not None:
            return CommandHandoff(
                HandoffStatus.PREPARING, preparing["command_id"], accepted_event_id
            )
    with _database(dsn, deployment_namespace).connect_task_io() as connection:
        connection.execute("SET LOCAL lock_timeout = '5s'")
        pending = connection.execute(
            """SELECT * FROM session_command_pending
               WHERE deployment_namespace = %s AND accepted_event_id = %s""",
            (deployment_namespace, accepted_event_id),
        ).fetchone()
        if (
            pending is None
            or pending["scope_key"] != command_scope_key(scope)
            or pending["tenant_id"] != scope.tenant_id
            or pending["workspace_id"] != scope.workspace_id
        ):
            raise ValueError("command handoff scope or canonical candidate mismatch")
        reject_missing_command_consumer(
            connection, deployment_namespace, accepted_event_id, consumer_capability
        )
        settled = settle_private_handoff(
            connection,
            deployment_namespace,
            scope,
            accepted_event_id,
            raw_body,
            required_scope_mode,
            pending,
            private,
        )
        if settled is not None:
            return settled
        require_private_handoff_preparation(
            connection, dsn, deployment_namespace, pending, private, private_preparation
        )
        if private and callable(private_preparation):
            private_preparation(connection, deployment_namespace, accepted_event_id)
        if not contained or private and callable(private_preparation):
            # ERP's ordinary private generation is gated; its coverage executor
            # remains unactivated, so never invoke a private coverage reader.
            coverage_check = prepare_command_handoff(
                None if private else coverage_check,
                connection,
                deployment_namespace,
                accepted_event_id,
                pending["current_generation"] if envelope is None else envelope.wake_generation,
            )
            connection = prepared_recovery_connection(connection, coverage_check)
        capability = pin_command_consumer(
            connection, deployment_namespace, accepted_event_id, consumer_capability
        )
        scope_result = defer_handoff_scope(
            connection,
            deployment_namespace,
            pending,
            required_scope_mode,
            accepted_event_id,
            command_scope_mode=command_scope_mode,
        )
        if scope_result is not None:
            return scope_result
        session_id = SessionId(pending["session_id"])
        lock_session_lease_boundary(connection, deployment_namespace, session_id)
        # No pending/Inbox lock before lease serialization: workers write those
        # after holding their existing lease SHARE and stream/projection locks.
        pending = connection.execute(
            """SELECT * FROM session_command_pending
               WHERE deployment_namespace = %s AND accepted_event_id = %s""",
            (deployment_namespace, accepted_event_id),
        ).fetchone()
        assert pending is not None
        outbox = connection.execute(
            """SELECT * FROM broker_outbox WHERE deployment_namespace = %s AND scope_key = %s
               AND message_type = 'zebra.session.command.ready' AND operation_id = %s
               AND wake_generation = %s""",
            (
                deployment_namespace,
                pending["scope_key"],
                pending["command_id"],
                pending["current_generation"] if envelope is None else envelope.wake_generation,
            ),
        ).fetchone()
        if outbox is None:
            raise ValueError("missing canonical command outbox")
        _validate(connection, deployment_namespace, pending, outbox, scope, raw_body)
        generation = outbox["wake_generation"]
        if generation < pending["current_generation"]:
            return CommandHandoff(HandoffStatus.DUPLICATE, pending["command_id"], accepted_event_id)
        if generation != pending["current_generation"]:
            raise ValueError("command generation has not been approved")
        retired = connection.execute(
            """SELECT 1 FROM command_retirements WHERE deployment_namespace=%s
               AND accepted_event_id=%s AND scope_key=%s AND session_id=%s AND command_id=%s""",
            (
                deployment_namespace,
                accepted_event_id,
                pending["scope_key"],
                session_id,
                pending["command_id"],
            ),
        ).fetchone()
        if retired is not None:
            return CommandHandoff(
                HandoffStatus.RETIRED_NOOP, pending["command_id"], accepted_event_id
            )
        approved = recovery_approval(
            connection, ZebraCommandEnvelope.model_validate(outbox["envelope_json"])
        )
        _check_inbox(connection, deployment_namespace, pending, outbox)
        receipt = connection.execute(
            """SELECT * FROM command_handoff_receipts WHERE deployment_namespace = %s
               AND scope_key = %s AND command_id = %s""",
            (deployment_namespace, pending["scope_key"], pending["command_id"]),
        ).fetchone()
        if receipt is not None and (
            receipt["accepted_event_id"] != accepted_event_id or receipt["session_id"] != session_id
        ):
            raise ValueError("canonical command receipt identity conflict")
        policy_result = check_handoff_policy(
            connection,
            dsn,
            deployment_namespace,
            session_id,
            accepted_event_id,
            pending,
            receipt,
            contained,
            private,
            private_preparation,
            capability,
            consumer_capability,
            pin_command_consumer=pin_command_consumer,
            terminal_session=_terminal_session,
        )
        if policy_result is not None:
            return policy_result
        coverage_proof = None
        if receipt is not None:
            if (
                receipt["accepted_event_id"] != accepted_event_id
                or receipt["session_id"] != session_id
            ):
                raise ValueError("canonical command receipt identity conflict")
            if receipt["wake_generation"] == generation or receipt["handled_event_id"] is not None:
                _inbox(connection, deployment_namespace, pending, outbox, receipt["status"])
                if capability is not None:
                    capability = pin_command_consumer(
                        connection,
                        deployment_namespace,
                        accepted_event_id,
                        consumer_capability,
                        lock_task_authority=True,
                    )
                    if capability is None:
                        raise WorkerCapabilityLostError(
                            "strict command identity changed before commit"
                        )
                    check_worker_capability_clock(connection, capability)
                status = (
                    HandoffStatus.DUPLICATE
                    if receipt["status"] == "accepted"
                    else HandoffStatus.REQUIRES_RECONCILIATION
                )
                return CommandHandoff(status, pending["command_id"], accepted_event_id)
        if approved is not None and approved["reason"] in {
            "coverage_checkpoint",
            "coverage_continuation",
        }:
            try:
                coverage_proof = verified_coverage_recovery(
                    connection, deployment_namespace, pending, receipt, coverage_check
                )
                coverage_generation_usage(
                    connection,
                    deployment_namespace,
                    pending,
                    coverage_proof,
                    maximum_crashes=MAX_GENERATION,
                )
                if (
                    approved["coverage_proof"] != coverage_proof
                    or receipt is None
                    or receipt["wake_generation"] != generation - 1
                    or approved["approved_stream_sequence"] != coverage_proof["stream_revision"]
                ):
                    raise ValueError("strict command recovery proof changed before handoff")
            except (ValueError, TypeError, KeyError):
                return CommandHandoff(
                    HandoffStatus.REQUIRES_RECONCILIATION, pending["command_id"], accepted_event_id
                )
        if receipt is not None:
            if (
                approved is None
                or receipt["wake_generation"] >= generation
                or (receipt["started_event_id"] is not None and coverage_proof is None)
                or receipt["status"] != "accepted"
            ):
                raise ValueError("command receipt cannot be rebound without recovery proof")
        event = connection.execute(
            """SELECT payload FROM session_events
               WHERE deployment_namespace = %s AND event_id = %s""",
            (deployment_namespace, accepted_event_id),
        ).fetchone()
        assert event is not None
        lease = None
        execution_floor = None
        input_event_id = None if receipt is None else receipt["input_event_id"]
        if (
            pending["origin"] != "live"
            or pending["status"] != "pending"
            or _terminal_session(connection, deployment_namespace, session_id)
        ):
            status = HandoffStatus.REQUIRES_RECONCILIATION
        elif event["payload"]["kind"] not in ("run", "resume", "message"):
            return CommandHandoff(
                HandoffStatus.UNSUPPORTED_FOR_EXECUTION_HANDOFF,
                pending["command_id"],
                accepted_event_id,
            )
        else:
            # Only an exact handled Event receipt unblocks the next command.
            # Neither projection sequence nor a merely accepted handoff suffices.
            prior = connection.execute(
                (
                    "SELECT event.event_id FROM session_events AS event WHERE deploym"
                    "ent_namespace = %s\n                   AND session_id = %s AND ev"
                    "ent_type = 'session_command_accepted'\n                   AND seq"
                    "uence < %s AND NOT EXISTS (\n                       SELECT 1 FROM"
                    " command_handoff_receipts AS receipt\n                       WHER"
                    "E receipt.deployment_namespace = event.deployment_namespace\n    "
                    "                     AND receipt.accepted_event_id = event.event"
                    "_id\n                         AND receipt.session_id = event.sess"
                    "ion_id AND receipt.scope_key = %s\n                         AND r"
                    "eceipt.status = 'accepted' AND receipt.handled_event_id IS NOT N"
                    "ULL\n                   ) AND NOT EXISTS (\n                      "
                    " SELECT 1 FROM command_control_receipts AS control\n             "
                    "          WHERE control.deployment_namespace = event.deployment_"
                    "namespace\n                         AND control.accepted_event_id"
                    " = event.event_id\n                         AND control.session_i"
                    "d = event.session_id AND control.scope_key = %s\n                "
                    "         AND control.kind = 'suspend' AND control.outcome = 'uns"
                    "upported'\n                   ) AND NOT EXISTS (\n                "
                    "       SELECT 1 FROM command_retirements AS retired\n            "
                    "           WHERE retired.deployment_namespace=event.deployment_n"
                    "amespace\n                         AND retired.accepted_event_id="
                    "event.event_id\n                         AND retired.session_id=e"
                    "vent.session_id AND retired.scope_key=%s\n                   ) OR"
                    "DER BY sequence"
                ),
                (
                    deployment_namespace,
                    session_id,
                    pending["accepted_sequence"],
                    pending["scope_key"],
                    pending["scope_key"],
                    pending["scope_key"],
                ),
            ).fetchall()
            from agent_storage.postgres.erp_fresh_disposition import verified_fresh_disposition

            # A dead text code cannot settle accepted work. Only the immutable,
            # fenced no-execution proof can discharge this historical command.
            try:
                unresolved = any(
                    verified_fresh_disposition(
                        connection,
                        deployment_namespace,
                        item["event_id"],
                        terminal=True,
                    )
                    is None
                    for item in prior
                )
            except (ValueError, TypeError, KeyError):
                unresolved = True
            if unresolved:
                return CommandHandoff(
                    HandoffStatus.PRIOR_COMMAND_UNRECONCILED,
                    pending["command_id"],
                    accepted_event_id,
                )
            if private:
                private_preparation(connection, deployment_namespace, accepted_event_id)
            try:
                # Nested transaction is a savepoint. An old writer may have held
                # lease SHARE while terminalizing the projection during our wait.
                # Re-read AFTER lease serialization, never lock projection first.
                with connection.transaction():
                    lease = acquire_lease_in_transaction(
                        connection,
                        deployment_namespace,
                        session_id,
                        owner_instance_id=owner_instance_id,
                        ttl=ttl,
                        maximum_ttl=maximum_ttl,
                    )
                    if _terminal_session(connection, deployment_namespace, session_id):
                        raise _TerminalAfterLease
                    # Freshness floor only: old Events cannot be attributed to
                    # this new fence. This is NOT a handled-command watermark.
                    stream = connection.execute(
                        """SELECT current_version FROM session_streams
                           WHERE deployment_namespace = %s AND session_id = %s FOR UPDATE""",
                        (deployment_namespace, session_id),
                    ).fetchone()
                    assert stream is not None
                    if (
                        approved is not None
                        and stream["current_version"] != approved["approved_stream_sequence"]
                    ):
                        raise _TerminalAfterLease
                    execution_floor = stream["current_version"]
                    if event["payload"]["kind"] == "message":
                        accepted = read_event_in_transaction(
                            connection, deployment_namespace, EventId(accepted_event_id)
                        )
                        assert accepted is not None
                        message = append_command_message(
                            connection,
                            deployment_namespace,
                            accepted,
                            input_event_id=input_event_id,
                        )
                        input_event_id = message.event_id
                        execution_floor = max(execution_floor, message.sequence)
            except LeaseConflictError:
                return CommandHandoff(HandoffStatus.BUSY, pending["command_id"], accepted_event_id)
            except CheckpointNotReady:
                return CommandHandoff(
                    HandoffStatus.PREPARING, pending["command_id"], accepted_event_id
                )
            except (_TerminalAfterLease, MessageInputRejected):
                lease = None
                execution_floor = None
                status = HandoffStatus.REQUIRES_RECONCILIATION
            else:
                status = HandoffStatus.ACCEPTED
        connection.execute(
            """INSERT INTO command_handoff_receipts (
                deployment_namespace, scope_key, command_id, accepted_event_id, session_id,
                status, control_plane_epoch, fencing_token, owner_instance_id,
                execution_floor_sequence, wake_generation, input_event_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (deployment_namespace, scope_key, command_id) DO UPDATE SET
                status = EXCLUDED.status, control_plane_epoch = EXCLUDED.control_plane_epoch,
                fencing_token = EXCLUDED.fencing_token,
                owner_instance_id = EXCLUDED.owner_instance_id,
                execution_floor_sequence = EXCLUDED.execution_floor_sequence,
                input_event_id = EXCLUDED.input_event_id,
                wake_generation = EXCLUDED.wake_generation, created_at = clock_timestamp(),
                started_event_id = NULL, handled_event_id = NULL, turn_id = NULL""",
            (
                deployment_namespace,
                pending["scope_key"],
                pending["command_id"],
                accepted_event_id,
                session_id,
                status.value,
                None if lease is None else lease.fence.control_plane_epoch,
                None if lease is None else lease.fence.fencing_token,
                None if lease is None else lease.fence.owner_instance_id,
                execution_floor,
                generation,
                input_event_id,
            ),
        )
        _inbox(connection, deployment_namespace, pending, outbox, status.value)
        if coverage_proof is not None:
            check_coverage_recovery_clock(connection, coverage_proof, pending=pending)
            if lease is not None:
                assert_current_lease_fence(
                    connection, deployment_namespace, session_id, lease.fence
                )
        if capability is not None:
            # Task61 is last, matching canonical Event allocation and renewal:
            # all Session/lease/stream/command writes precede the locked recheck.
            capability = pin_command_consumer(
                connection,
                deployment_namespace,
                accepted_event_id,
                consumer_capability,
                lock_task_authority=True,
            )
            if capability is None:
                raise WorkerCapabilityLostError("strict command identity changed before commit")
            check_worker_capability_clock(connection, capability)
        if coverage_proof is not None:
            check_prepared_recovery_clock(
                connection, coverage_check, proof=coverage_proof, pending=pending
            )
        return CommandHandoff(status, pending["command_id"], accepted_event_id, lease)
