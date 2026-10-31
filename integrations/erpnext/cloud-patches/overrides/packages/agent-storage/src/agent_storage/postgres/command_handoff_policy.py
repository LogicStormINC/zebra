from agent_core.domain.identifiers import SessionId
from agent_storage.postgres.command_handoff_types import CommandHandoff as CommandHandoff
from agent_storage.postgres.command_handoff_types import HandoffStatus as HandoffStatus
from agent_storage.postgres.worker_capability import (
    WorkerCapabilityLostError,
    check_worker_capability_clock,
)


def check_handoff_policy(
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
    *,
    pin_command_consumer,
    terminal_session,
):
    from agent_storage.postgres.erp_workspace_policy import (
        ERPWorkspacePolicyRefusal,
        containment_for_database,
    )
    from agent_storage.postgres.leases import read_current_lease

    policy = containment_for_database(dsn, deployment_namespace) if contained else None
    if contained and policy is None:
        raise ValueError("ERP containment policy is unavailable")
    if policy is not None:
        event = connection.execute(
            "SELECT payload FROM session_events WHERE deployment_namespace=%s AND event_id=%s",
            (deployment_namespace, accepted_event_id),
        ).fetchone()
        if event is None:
            raise ValueError("canonical command Event is absent")
        if event["payload"].get("kind") not in {"run", "resume", "message"}:
            return CommandHandoff(
                HandoffStatus.UNSUPPORTED_FOR_EXECUTION_HANDOFF,
                pending["command_id"],
                accepted_event_id,
            )
        if receipt is not None and receipt["handled_event_id"] is not None:
            return CommandHandoff(HandoffStatus.DUPLICATE, pending["command_id"], accepted_event_id)
        try:
            policy.require(session_id)
        except ERPWorkspacePolicyRefusal as refusal:
            # Do not overwrite a concurrent active fence, control receipt,
            # or any accepted/Started/handled execution history.
            if (
                read_current_lease(connection, deployment_namespace, session_id) is None
                and not terminal_session(connection, deployment_namespace, session_id)
                and (receipt is None or receipt["started_event_id"] is None)
            ):
                connection.execute(
                    (
                        "UPDATE session_command_pending SET status='dead', recovery_code="
                        "%s WHERE deployment_namespace=%s AND accepted_event_id=%s AND st"
                        "atus='pending'"
                    ),
                    (refusal.code, deployment_namespace, accepted_event_id),
                )
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
                        "strict command identity changed before refusal"
                    ) from refusal
                check_worker_capability_clock(connection, capability)
            return CommandHandoff(
                HandoffStatus.REQUIRES_RECONCILIATION, pending["command_id"], accepted_event_id
            )
        if not private:
            raise ValueError("ERP containment requires an explicit policy refusal")
        if not callable(private_preparation):
            from agent_storage.postgres.coverage_recovery_preparation import (
                CoverageRecoveryDeferred,
            )

            raise CoverageRecoveryDeferred("private preparation proof is missing")
        private_preparation(connection, deployment_namespace, accepted_event_id)
    return None


def require_private_handoff_preparation(
    connection, dsn, deployment_namespace, pending, private, private_preparation
):
    if private and not callable(private_preparation):
        from agent_storage.postgres.coverage_recovery_preparation import (
            CoverageRecoveryDeferred,
        )
        from agent_storage.postgres.erp_workspace_policy import (
            ERPWorkspacePolicyRefusal,
            containment_for_database,
        )

        missing_policy = containment_for_database(dsn, deployment_namespace)
        if missing_policy is None:
            raise ValueError("private preparation native policy is unavailable")
        try:
            missing_policy.require_in_transaction(connection, SessionId(pending["session_id"]))
        except ERPWorkspacePolicyRefusal:
            pass  # Preserve canonical observation-only refusal below.
        else:
            raise CoverageRecoveryDeferred("private preparation proof is missing")


def settle_private_handoff(
    connection,
    deployment_namespace,
    scope,
    accepted_event_id,
    raw_body,
    required_scope_mode,
    pending,
    private,
):
    if private:
        from agent_storage.postgres.erp_private_workspace import private_command_settlement

        settled = private_command_settlement(
            connection,
            deployment_namespace,
            scope,
            accepted_event_id,
            raw_body,
            required_scope_mode,
        )
        if settled is not None:
            return CommandHandoff(HandoffStatus(settled), pending["command_id"], accepted_event_id)
    return None


def defer_handoff_scope(
    connection,
    deployment_namespace,
    pending,
    required_scope_mode,
    accepted_event_id,
    *,
    command_scope_mode,
):
    if required_scope_mode is not None:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,50))",
            (f"{deployment_namespace}:command-rollout:{pending['scope_key']}",),
        )
        mode = command_scope_mode(connection, deployment_namespace, pending["scope_key"])
        if required_scope_mode == "fallback" and mode == "broker":
            return CommandHandoff(
                HandoffStatus.SCOPE_DEFERRED, pending["command_id"], accepted_event_id
            )
        if required_scope_mode == "broker" and mode != "broker":
            status = (
                HandoffStatus.SCOPE_DEFERRED
                if pending["status"] == "pending"
                else HandoffStatus.SCOPE_SETTLED
            )
            return CommandHandoff(status, pending["command_id"], accepted_event_id)
    return None
