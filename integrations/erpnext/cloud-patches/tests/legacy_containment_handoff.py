"""Modern command containment and real native Coverage preparation scenarios."""

import os
from contextlib import ExitStack
from datetime import timedelta
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from uuid import uuid4

from agent_core.contracts.broker_envelope import PrincipalScope
from agent_core.domain.events import EventType
from agent_storage.postgres import command_read_preflight as preflight
from agent_storage.postgres import command_wakeup_handoff as handoff
from agent_storage.postgres import erp_workspace_policy as policy
from agent_storage.postgres.command_wakeup import command_scope_key


def check_command_handoff(Database, NOW, REF, Row, SID, lease):
    # Modern prelude never enters MESSAGE preparation; formal handoff writes only
    # exact dead/code metadata, without touching receipts or acquiring a new fence.
    scope = PrincipalScope(kind="principal", tenant_id="erpnext", workspace_id=REF)
    EID, CID = uuid4(), uuid4()
    pending = dict(
        scope_key=command_scope_key(scope),
        tenant_id="erpnext",
        workspace_id=REF,
        session_id=SID,
        accepted_event_id=EID,
        command_id=CID,
        current_generation=0,
        status="pending",
        origin="live",
        command_kind="message",
        accepted_sequence=2,
    )
    outbox = dict(
        wake_generation=0,
        envelope_json=dict(
            message_id=str(uuid4()),
            schema_version=1,
            deployment_namespace="erpnext",
            aggregate_id=str(SID),
            operation_id=str(CID),
            wake_generation=0,
            idempotency_key="qa",
            correlation_id="qa",
            causation_id=None,
            occurred_at=NOW.isoformat(),
            traceparent=None,
            payload_ref=dict(kind="zebra_command", id=str(CID)),
            message_type="zebra.session.command.ready",
            scope=scope.model_dump(),
            accepted_event_id=str(EID),
            accepted_sequence=2,
        ),
    )

    class Commands:
        def __init__(self, receipt=None, active=False, terminal=False):
            self.pending = dict(pending)
            self.receipt = (
                dict(receipt, accepted_event_id=EID, session_id=SID)
                if receipt is not None
                else None
            )
            self.active = active
            self.terminal = terminal
            self.writes = []

        def execute(self, sql, args=()):
            if "FROM session_command_pending" in sql:
                return Row(self.pending)
            if "FROM broker_outbox" in sql:
                return Row(outbox)
            if "FROM command_retirements" in sql:
                return Row(None)
            if "FROM command_handoff_receipts" in sql:
                return Row(self.receipt)
            if "SELECT payload FROM session_events" in sql:
                return Row({"payload": {"kind": "message"}})
            if sql.startswith("UPDATE session_command_pending"):
                if self.pending["status"] == "pending":
                    self.pending.update(status="dead", recovery_code=args[0])
                    self.writes.append((sql, args))
                return Row(None)
            if sql.startswith("SET LOCAL") or "pg_advisory_xact_lock" in sql:
                return Row(None)
            raise AssertionError(sql)

    with ExitStack() as stack, patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: "enabled"}):
        for module, name, value in (
            (handoff, "_validate", None),
            (handoff, "_check_inbox", None),
            (handoff, "reject_missing_command_consumer", None),
            (handoff, "pin_command_consumer", None),
            (handoff, "recovery_approval", None),
        ):
            stack.enter_context(
                patch.object(
                    module,
                    name,
                    side_effect=(lambda c, *a: c) if value == "connection" else None,
                    return_value=value,
                )
            )
        stack.enter_context(
            patch.object(
                handoff,
                "prepare_command_handoff",
                side_effect=AssertionError("coverage preparation"),
            )
        )
        stack.enter_context(
            patch.object(
                handoff,
                "prepared_recovery_connection",
                side_effect=AssertionError("prepared recovery wrapper"),
            )
        )
        guard = NS(
            require=Mock(
                side_effect=policy.ERPWorkspacePolicyRefusal(policy.LEGACY_OBSERVATION_ONLY)
            )
        )
        stack.enter_context(patch.object(policy, "containment_for_database", return_value=guard))
        acquire = stack.enter_context(
            patch.object(
                handoff, "acquire_lease_in_transaction", side_effect=AssertionError("lease")
            )
        )
        append = stack.enter_context(
            patch.object(handoff, "append_command_message", side_effect=AssertionError("MESSAGE"))
        )
        for receipt, active, terminal, expected in (
            (None, False, False, 1),
            (None, True, False, 0),
            (dict(handled_event_id=uuid4()), False, False, 0),
            (dict(handled_event_id=None, started_event_id=uuid4()), False, False, 0),
            (None, False, True, 0),
        ):
            connection = Commands(receipt, active, terminal)
            with (
                patch.object(handoff, "_database", return_value=Database(connection)),
                patch.object(
                    handoff,
                    "prepare_command_candidate",
                    side_effect=AssertionError("candidate preparation"),
                ),
                patch(
                    "agent_storage.postgres.leases.read_current_lease",
                    return_value=lease if active else None,
                ),
                patch.object(handoff, "_terminal_session", return_value=terminal),
            ):
                for _ in range(2):
                    result = handoff.handoff_command(
                        "qa",
                        deployment_namespace="erpnext",
                        scope=scope,
                        accepted_event_id=EID,
                        owner_instance_id="qa",
                        ttl=timedelta(seconds=30),
                    )
                    assert result.lease is None
                assert len(connection.writes) == expected
                if expected:
                    assert connection.pending["recovery_code"] == policy.LEGACY_OBSERVATION_ONLY
        assert not acquire.called and not append.called
        connection = Commands()
        event = NS(event_type=EventType.SESSION_COMMAND_ACCEPTED, payload={"kind": "message"})
        with (
            patch.object(preflight, "_database", return_value=Database(connection)),
            patch.object(preflight, "command_event_at", return_value=event),
            patch.object(preflight, "finish_command_read_state") as finish,
            patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: "enabled"}),
        ):
            assert (
                preflight.prepare_command_candidate(
                    "qa", "erpnext", scope, EID, None, 0, None, message_only=True
                )
                is None
            )
            assert not finish.called and not connection.writes
    # Regression: real NativeCoverageRecoveryCheck must not enter preparation before
    # containment. Its original prepare/_prepare chain is supplied intact; forbidden
    # boundaries fail loudly instead of returning the old test's harmless None.
    native_recovery = __import__(
        "zebra_agent_worker", fromlist=("coverage_recovery",)
    ).coverage_recovery
    NativeCoverageRecoveryCheck = __import__(
        "zebra_agent_worker.coverage_recovery_preparation",
        fromlist=("NativeCoverageRecoveryCheck",),
    ).NativeCoverageRecoveryCheck
    RecoveryArtifactReads = __import__(
        "zebra_agent_worker.coverage_recovery_preparation", fromlist=("RecoveryArtifactReads",)
    ).RecoveryArtifactReads

    native_database = NS(
        connect=Mock(side_effect=AssertionError("native recovery preparation entered"))
    )
    checker = NativeCoverageRecoveryCheck(
        NS(deployment_namespace="erpnext", metadata=NS(_database=native_database)), NS()
    )
    original_prepare = NativeCoverageRecoveryCheck.prepare
    with ExitStack() as stack:
        prepare_spy = stack.enter_context(
            patch.object(
                NativeCoverageRecoveryCheck, "prepare", autospec=True, side_effect=original_prepare
            )
        )
        forbidden = [
            stack.enter_context(
                patch.object(
                    module,
                    name,
                    side_effect=AssertionError("forbidden containment boundary: " + name),
                )
            )
            for module, name in (
                (native_recovery, "prepare_recovery_authority"),
                (native_recovery, "frozen_or_discovered_manifest"),
                (native_recovery.HostCoverageSnapshotSource, "_get_descriptor"),
                (native_recovery, "load_official_model_policy"),
                (RecoveryArtifactReads, "_read_record"),
            )
        ]
        candidate = stack.enter_context(
            patch.object(
                handoff,
                "prepare_command_candidate",
                side_effect=AssertionError("candidate preparation entered"),
            )
        )
        # These are pure native SQL security checks, retained before denial. Keep
        # the real functions and observe them; a non-strict command yields no pin.
        security_reject = stack.enter_context(
            patch.object(
                handoff,
                "reject_missing_command_consumer",
                wraps=handoff.reject_missing_command_consumer,
            )
        )
        security_pin = stack.enter_context(
            patch.object(handoff, "pin_command_consumer", wraps=handoff.pin_command_consumer)
        )
        for name in ("_validate", "_check_inbox", "recovery_approval"):
            stack.enter_context(patch.object(handoff, name, return_value=None))
        stack.enter_context(patch.object(policy, "containment_for_database", return_value=guard))
        stack.enter_context(
            patch("agent_storage.postgres.leases.read_current_lease", return_value=None)
        )
        stack.enter_context(patch.object(handoff, "_terminal_session", return_value=False))

        class StrictCommands(Commands):
            def execute(self, sql, args=()):
                if "SELECT 1 FROM command_coverage_requirements" in sql:
                    return Row(None)
                if "SELECT session_id,payload FROM session_events" in sql:
                    return Row(dict(session_id=SID, payload={"kind": "message"}))
                if "SELECT t.task_id,t.root_session_id" in sql:
                    return Row(None)
                return super().execute(sql, args)

        connection = StrictCommands()
        with (
            patch.object(handoff, "_database", return_value=Database(connection)),
            patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: "enabled"}),
        ):
            result = handoff.handoff_command(
                "qa",
                deployment_namespace="erpnext",
                scope=scope,
                accepted_event_id=EID,
                owner_instance_id="qa",
                ttl=timedelta(seconds=30),
                coverage_check=checker,
            )
            assert result.status is handoff.HandoffStatus.REQUIRES_RECONCILIATION
            assert connection.pending["recovery_code"] == policy.LEGACY_OBSERVATION_ONLY
        assert security_reject.call_count == 1 and security_pin.call_count == 1
        assert (
            not candidate.called and not prepare_spy.called and not native_database.connect.called
        )
        assert all(not boundary.called for boundary in forbidden)
        # Canonical validation still precedes denial/ACK; malformed candidates
        # cannot use containment to acquire an apparently valid terminal outcome.
        connection = StrictCommands()
        previous_refusals = guard.require.call_count
        with (
            patch.object(handoff, "_database", return_value=Database(connection)),
            patch.object(handoff, "_validate", side_effect=ValueError("canonical mismatch")),
            patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: "enabled"}),
        ):
            try:
                handoff.handoff_command(
                    "qa",
                    deployment_namespace="erpnext",
                    scope=scope,
                    accepted_event_id=EID,
                    owner_instance_id="qa",
                    ttl=timedelta(seconds=30),
                    coverage_check=checker,
                )
            except ValueError as error:
                assert str(error) == "canonical mismatch"
            else:
                raise AssertionError("Unvalidated canonical command was ACKed")
        assert not connection.writes and guard.require.call_count == previous_refusals

        class ControlCommands(StrictCommands):
            def execute(self, sql, args=()):
                if "SELECT payload FROM session_events" in sql:
                    return Row({"payload": {"kind": "stop"}})
                return super().execute(sql, args)

        connection = ControlCommands()
        with (
            patch.object(handoff, "_database", return_value=Database(connection)),
            patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: "enabled"}),
        ):
            result = handoff.handoff_command(
                "qa",
                deployment_namespace="erpnext",
                scope=scope,
                accepted_event_id=EID,
                owner_instance_id="qa",
                ttl=timedelta(seconds=30),
                coverage_check=checker,
            )
            assert result.status is handoff.HandoffStatus.UNSUPPORTED_FOR_EXECUTION_HANDOFF
        assert not connection.writes and guard.require.call_count == previous_refusals
        # A qualified strict consumer is re-pinned and checked AFTER tentative
        # metadata writes. Expiry must raise so the real outer transaction rolls back.
        connection = StrictCommands()
        capability = NS()
        with (
            patch.object(handoff, "_database", return_value=Database(connection)),
            patch.object(handoff, "pin_command_consumer", return_value=capability) as pin,
            patch.object(
                handoff,
                "check_worker_capability_clock",
                side_effect=handoff.WorkerCapabilityLostError("expired"),
            ) as clock,
            patch(
                "agent_storage.postgres.command_handoff_policy.check_worker_capability_clock",
                new=clock,
            ),
            patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: "enabled"}),
        ):
            try:
                handoff.handoff_command(
                    "qa",
                    deployment_namespace="erpnext",
                    scope=scope,
                    accepted_event_id=EID,
                    owner_instance_id="qa",
                    ttl=timedelta(seconds=30),
                    coverage_check=checker,
                )
            except handoff.WorkerCapabilityLostError:
                pass
            else:
                raise AssertionError("Expired capability committed a refusal")
            assert len(connection.writes) == 1 and pin.call_count == 2 and clock.call_count == 1
            assert pin.call_args.kwargs == {"lock_task_authority": True}
        assert (
            not candidate.called and not prepare_spy.called and not native_database.connect.called
        )
        assert all(not boundary.called for boundary in forbidden)
        # Disabled keeps candidate -> security -> native prepare ordering. The real
        # native prepare/_prepare chain reaches its DB boundary and stops at a strict
        # sentinel, before any real I/O can occur in this assertion-only check.
        order = []
        candidate.side_effect = lambda *args, **kwargs: order.append("candidate")
        security_reject.side_effect = lambda *args, **kwargs: order.append("security")

        def enter_native(self, *args, **kwargs):
            order.append("native_prepare")
            return original_prepare(self, *args, **kwargs)

        prepare_spy.side_effect = enter_native
        with (
            patch.object(handoff, "_database", return_value=Database(StrictCommands())),
            patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: "disabled"}),
        ):
            try:
                handoff.handoff_command(
                    "qa",
                    deployment_namespace="erpnext",
                    scope=scope,
                    accepted_event_id=EID,
                    owner_instance_id="qa",
                    ttl=timedelta(seconds=30),
                    coverage_check=checker,
                )
            except AssertionError as error:
                assert str(error) == "native recovery preparation entered"
            else:
                raise AssertionError("Disabled native preparation was silently skipped")
        assert order == ["candidate", "security", "native_prepare"], order
        assert prepare_spy.call_count == 1 and native_database.connect.call_count == 1
        assert all(not boundary.called for boundary in forbidden)
