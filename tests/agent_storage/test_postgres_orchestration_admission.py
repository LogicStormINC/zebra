"""03B real PostgreSQL: original admission, shared budget and trusted settlement."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import TaskId
from agent_core.domain.subagent_delegation import SubagentDelegationRequest
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_orchestration.application.orchestration_admission import (
    PreparedOrchestrationChild,
    derive_orchestration_child_binding,
    original_key,
)
from agent_orchestration.application.orchestration_authority import OrchestrationAuthority
from agent_orchestration.application.orchestration_port import OrchestrationToolError
from agent_orchestration.application.orchestration_runtime import OrchestrationRuntime
from agent_orchestration.application.orchestration_validation import PlanValidationContext
from agent_orchestration.domain.orchestration import (
    OrchestrationNodeProposal,
    OrchestrationPlanProposal,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation, BudgetUsageReceipt
from agent_storage import apply_postgres_migrations, bootstrap_control_plane_epoch
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import acquire_lease_in_transaction
from agent_storage.postgres.orchestration import PostgresOrchestrationStore
from agent_storage.postgres.orchestration_admission import PostgresOrchestrationAdmission
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from agent_storage.postgres.work_unit import postgres_work_unit

from tests.agent_storage.test_command_wakeup import _binding


@pytest.fixture(scope="module")
def dsn():
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN for owned real PostgreSQL")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def setup(dsn):
    ns = "orch-admit-" + str(uuid4())
    bootstrap_control_plane_epoch(dsn, deployment_namespace=ns)
    boot = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Parent",
            user_input="Analyze",
            workspace_root="/tmp/orchestration-parent",
        )
    )
    parent = _binding(str(boot.session.session_id))
    PostgresTaskAdmissionTransaction(dsn, deployment_namespace=ns).admit(
        TaskAdmissionRequest(
            events=boot.events,
            session=boot.session,
            workspace=rebuild_workspace(list(boot.events)),
            binding=parent,
        )
    )
    authority = OrchestrationAuthority(
        parent_task_id=TaskId(boot.session.session_id),
        parent_binding_digest=parent.binding_digest,
        deployment_namespace=ns,
        approved_budget=BudgetReservation(model_tokens=100, tool_calls=20, runtime_seconds=60),
        validation=PlanValidationContext(
            parent_capabilities=frozenset({"agent.execute"}),
            parent_remaining_budget=BudgetReservation(
                model_tokens=100, tool_calls=20, runtime_seconds=60
            ),
        ),
    )
    return dsn, ns, authority


def _build(authority, parent, snapshot, node):
    key = original_key(authority.deployment_namespace, snapshot, node.node_key)
    delegation = SubagentDelegationRequest(
        parent_task_id=authority.parent_task_id,
        parent_attempt_number=1,
        parent_tool_call_id=key,
        delegation_index=0,
        role=node.preferred_agent_role,
        objective=node.objective,
        requested_capabilities=node.required_capabilities,
        resource_refs=node.resource_refs,
        isolation_mode=node.isolation_mode,
        child_definition_snapshot_digest="a" * 64,
        child_capability_profile_ref="researcher@1",
        expected_parent_binding_digest=authority.parent_binding_digest,
    )
    # Derive the exact Host limit narrowing before bootstrapping the child.
    probe = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Child",
            user_input=node.objective,
            workspace_root="/tmp/orchestration-child",
        )
    )
    provisional = derive_orchestration_child_binding(
        parent, delegation, probe.session.session_id, node
    )
    boot = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Child",
            user_input=node.objective,
            workspace_root="/tmp/orchestration-child",
            max_model_calls=node.max_model_calls,
            max_tool_calls=node.max_tool_calls,
            host_context=provisional.host_capability.host_context,
        )
    )
    binding = derive_orchestration_child_binding(parent, delegation, boot.session.session_id, node)
    command = SessionCommand(
        session_id=boot.session.session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=boot.events[-1].sequence,
        idempotency_key=key,
    )
    event = SessionEvent.create(
        session_id=boot.session.session_id,
        sequence=len(boot.events),
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.HARNESS,
        payload=command.event_payload(),
        idempotency_key=key,
    )
    return PreparedOrchestrationChild(
        delegation,
        TaskAdmissionRequest(
            events=(*boot.events, event),
            session=boot.session,
            workspace=rebuild_workspace(list(boot.events)),
            binding=binding,
        ),
    )


def _run(setup, tokens=60):
    dsn, ns, authority = setup
    store = PostgresOrchestrationStore(dsn, deployment_namespace=ns)
    runtime = OrchestrationRuntime(store, authorize=lambda action: nullcontext(authority))
    receipt = runtime.propose_plan(
        OrchestrationPlanProposal(
            objective="Analyze",
            nodes=(
                OrchestrationNodeProposal(
                    node_key="a",
                    objective="Collect sources",
                    preferred_agent_role="researcher",
                    required_capabilities=frozenset({"agent.execute"}),
                    max_model_tokens=tokens,
                    max_model_calls=2,
                    max_tool_calls=3,
                    max_runtime_seconds=10,
                ),
            ),
            max_parallelism=1,
            synthesis_instruction="Merge",
        )
    )
    runtime.materialize(receipt.run_ref)
    snapshot = store.get_snapshot(receipt.run_ref)
    return receipt.run_ref, original_key(ns, snapshot, "a")


def _service(setup, cls=PostgresOrchestrationAdmission, **kwargs):
    dsn, ns, authority = setup
    return cls(
        dsn,
        deployment_namespace=ns,
        authorize=lambda action: nullcontext(authority),
        build_child=_build,
        executor_budget_ready=kwargs.pop("executor_budget_ready", lambda authority, node: True),
        **kwargs,
    )


def _count(setup, table):
    dsn, ns, _ = setup
    with psycopg.connect(dsn) as connection:
        return connection.execute(
            f"SELECT count(*) FROM {table} WHERE deployment_namespace=%s", (ns,)
        ).fetchone()[0]


def _stop(setup):
    dsn, ns, authority = setup
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """INSERT INTO agent_safety_overrides
               (deployment_namespace,session_id,kind,reason,diagnostics,created_at,updated_at)
               VALUES(%s,%s,'watchdog','user_force_stop',%s,clock_timestamp(),clock_timestamp())""",
            (
                ns,
                authority.parent_task_id,
                json.dumps(
                    {
                        "task_id": str(authority.parent_task_id),
                        "binding_digest": authority.parent_binding_digest,
                    }
                ),
            ),
        )


def test_real_child_initial_run_lineage_node_and_original_replay(setup):
    run, key = _run(setup)
    service = _service(setup)
    first = service.request_task(run_ref=run, node_key="a")
    assert service.request_task(run_ref=run, node_key="a") == first
    original = service.observe(key)
    assert (
        original["state"] == "admitted"
        and original["receipt"]["child_task_id"] == first.child_task_id
    )
    assert _count(setup, "agent_tasks") == 2
    dsn, ns, _ = setup
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT child_task_id FROM orchestration_nodes WHERE "
            "deployment_namespace=%s AND run_id=%s",
            (ns, run),
        ).fetchone()[0] == UUID(first.child_task_id)
        assert (
            connection.execute(
                "SELECT count(*) FROM session_events WHERE deployment_namespace=%s "
                "AND session_id=%s AND event_type=%s",
                (ns, first.child_task_id, EventType.SESSION_COMMAND_ACCEPTED.value),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT node_key FROM subagent_delegation_links WHERE "
                "deployment_namespace=%s AND child_task_id=%s",
                (ns, first.child_task_id),
            ).fetchone()[0]
            == "a"
        )


def test_concurrent_same_node_materializes_one_child(setup):
    run, key = _run(setup)
    barrier = Barrier(2)

    def request():
        barrier.wait()
        try:
            return _service(setup).request_task(run_ref=run, node_key="a")
        except OrchestrationToolError as error:
            assert error.reason_code == "orchestration_admission_unknown"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: request(), range(2)))
    assert any(results)
    assert _count(setup, "agent_tasks") == 2
    assert _service(setup).observe(key)["state"] == "admitted"


def test_shared_parent_budget_across_runs_does_not_reset(setup):
    one, _ = _run(setup)
    two, _ = _run(setup)
    _service(setup).request_task(run_ref=one, node_key="a")
    with pytest.raises(OrchestrationToolError, match="budget_beyond_parent"):
        _service(setup).request_task(run_ref=two, node_key="a")
    assert _count(setup, "agent_tasks") == 2
    assert _count(setup, "orchestration_admission_originals") == 1


def test_crash_after_prepare_is_unknown_and_never_retried(setup):
    run, key = _run(setup)

    class Crashed(PostgresOrchestrationAdmission):
        def _execute(self, key, prepared):
            raise OSError("lost before admission")

    with pytest.raises(OrchestrationToolError, match="admission_unknown"):
        _service(setup, Crashed).request_task(run_ref=run, node_key="a")
    restarted = _service(setup)
    assert restarted.observe(key)["state"] == "prepared"
    with pytest.raises(OrchestrationToolError, match="admission_unknown"):
        restarted.request_task(run_ref=run, node_key="a")
    assert _count(setup, "agent_tasks") == 1
    assert not restarted.settle(key)
    other, _ = _run(setup)
    with pytest.raises(OrchestrationToolError, match="budget_beyond_parent"):
        restarted.request_task(run_ref=other, node_key="a")


def test_lost_success_reply_observes_original_real_child(setup):
    run, key = _run(setup)

    class ReplyLost(PostgresOrchestrationAdmission):
        def _execute(self, key, prepared):
            super()._execute(key, prepared)
            raise OSError("reply lost after commit")

    with pytest.raises(OrchestrationToolError, match="admission_unknown"):
        _service(setup, ReplyLost).request_task(run_ref=run, node_key="a")
    restarted = _service(setup)
    original = restarted.observe(key)
    assert original["state"] == "admitted"
    assert (
        restarted.request_task(run_ref=run, node_key="a").child_task_id
        == original["receipt"]["child_task_id"]
    )
    assert _count(setup, "agent_tasks") == 2


def test_stop_before_admission_rejects_and_descendant_stop_refuses_lease(setup):
    run, key = _run(setup)
    child = _service(setup).request_task(run_ref=run, node_key="a")
    _stop(setup)
    dsn, ns, _ = setup
    from uuid import UUID

    from agent_core.domain.leases import LeaseConflictError

    with psycopg.connect(dsn) as connection, pytest.raises(LeaseConflictError, match="stop"):
        acquire_lease_in_transaction(
            connection,
            ns,
            UUID(child.child_task_id),
            owner_instance_id="worker",
            ttl=timedelta(seconds=10),
        )
    other, _ = _run(setup)
    with pytest.raises(OrchestrationToolError, match="orchestration_forbidden"):
        _service(setup).request_task(run_ref=other, node_key="a")
    assert _count(setup, "agent_tasks") == 2


def test_parent_binding_drift_and_ambient_transaction_fail_closed(setup):
    run, _ = _run(setup)
    dsn, ns, _ = setup
    with postgres_work_unit(PostgresDatabase(dsn, deployment_namespace=ns)):
        with pytest.raises(OrchestrationToolError, match="transaction_scope"):
            _service(setup).request_task(run_ref=run, node_key="a")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE task_binding_snapshots SET binding_digest=%s WHERE deployment_namespace=%s",
            ("f" * 64, ns),
        )
    with pytest.raises(OrchestrationToolError, match="orchestration_forbidden"):
        _service(setup).request_task(run_ref=run, node_key="a")
    assert _count(setup, "agent_tasks") == 1


def test_terminal_usage_settles_once_and_conflicting_receipt_refused(setup):
    run, key = _run(setup)
    child = _service(setup).request_task(run_ref=run, node_key="a")
    usage = BudgetUsageReceipt(
        child_task_ref=child.child_task_id, model_tokens=10, tool_calls=1, runtime_seconds=2
    )
    current = [usage]
    service = _service(setup, usage_reader=lambda con, child: current[0])
    assert not service.settle(key)  # terminal status alone is not a usage receipt
    dsn, ns, _ = setup
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_projections SET status='completed' WHERE "
            "deployment_namespace=%s AND session_id=%s",
            (ns, child.child_task_id),
        )
    assert service.settle(key) and service.settle(key)
    assert service.observe(key)["usage"]["model_tokens"] == 10
    current[0] = usage.model_copy(update={"model_tokens": 11})
    with pytest.raises(OrchestrationToolError, match="usage_conflict"):
        service.settle(key)
    other, _ = _run(setup)
    assert service.request_task(run_ref=other, node_key="a")


def _process_request(setup, run, barrier, queue):
    barrier.wait(timeout=10)
    try:
        result = _service(setup).request_task(run_ref=run, node_key="a")
        queue.put(("admitted", result.child_task_id))
    except OrchestrationToolError as error:
        queue.put((error.reason_code, None))


def test_two_independent_processes_resolve_one_original(setup):
    import multiprocessing

    run, key = _run(setup)
    ctx = multiprocessing.get_context("spawn")
    queue, barrier = ctx.Queue(), ctx.Barrier(2)
    processes = [
        ctx.Process(target=_process_request, args=(setup, run, barrier, queue)) for _ in range(2)
    ]
    try:
        for process in processes:
            process.start()
        results = [queue.get(timeout=15) for _ in processes]
        assert all(kind in {"admitted", "orchestration_admission_unknown"} for kind, _ in results)
        assert any(kind == "admitted" for kind, _ in results)
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
        assert _count(setup, "agent_tasks") == 2
        assert _service(setup).observe(key)["state"] == "admitted"
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()
        queue.join_thread()


def test_failure_after_child_admission_rolls_back_child_but_keeps_original_reservation(setup):
    run, key = _run(setup)
    service = _service(setup)
    delegate = service._delegation.delegate

    def lost(request, admission):
        delegate(request, admission)
        raise RuntimeError("failure after real child rows")

    service._delegation.delegate = lost
    with pytest.raises(OrchestrationToolError, match="admission_unknown"):
        service.request_task(run_ref=run, node_key="a")
    assert _count(setup, "agent_tasks") == 1
    original = _service(setup).observe(key)
    assert original["state"] == "prepared" and original["usage"] is None


def test_prepare_commit_reply_loss_preserves_unknown_original(setup):
    from contextlib import contextmanager

    run, key = _run(setup)

    class PrepareReplyLost(PostgresOrchestrationAdmission):
        phases = 0

        @contextmanager
        def _phase(self, *, active):
            self.phases += 1
            phase = self.phases
            with super()._phase(active=active) as value:
                yield value
            if phase == 2:
                raise OSError("prepare committed but reply was lost")

    with pytest.raises(OrchestrationToolError, match="admission_unknown"):
        _service(setup, PrepareReplyLost).request_task(run_ref=run, node_key="a")
    assert _service(setup).observe(key)["state"] == "prepared"
    assert _count(setup, "agent_tasks") == 1


@pytest.mark.parametrize("change", ["payload", "plan"])
def test_original_payload_or_plan_changes_are_conflicts(setup, change):
    run, key = _run(setup)
    _service(setup).request_task(run_ref=run, node_key="a")
    dsn, ns, _ = setup
    with psycopg.connect(dsn) as connection:
        if change == "payload":
            connection.execute(
                "UPDATE orchestration_admission_originals SET payload_digest=%s "
                "WHERE deployment_namespace=%s AND original_key=%s",
                ("0" * 64, ns, key),
            )
        else:
            connection.execute(
                "UPDATE orchestration_plan_revisions SET snapshot_json=jsonb_set(snapshot_json,"
                "'{nodes,0,proposal,objective}',to_jsonb(%s::text)) WHERE "
                "deployment_namespace=%s AND run_id=%s",
                ("changed", ns, run),
            )
    with pytest.raises(OrchestrationToolError, match="original_conflict"):
        _service(setup).observe(key)
    assert _count(setup, "agent_tasks") == 2


@pytest.mark.parametrize("change", ["status", "binding", "segment"])
def test_usage_reader_cannot_move_child_before_settlement(setup, change):
    run, key = _run(setup)
    child = _service(setup).request_task(run_ref=run, node_key="a")
    dsn, ns, _ = setup
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_projections SET status='completed' WHERE "
            "deployment_namespace=%s AND session_id=%s",
            (ns, child.child_task_id),
        )

    def reader(connection, child_id):
        if change == "status":
            connection.execute(
                "UPDATE session_projections SET status='running' WHERE "
                "deployment_namespace=%s AND session_id=%s",
                (ns, child_id),
            )
        elif change == "binding":
            connection.execute(
                "UPDATE task_binding_snapshots SET snapshot_json=jsonb_set("
                "snapshot_json,'{zebra_policy_digest}',to_jsonb(%s::text)) WHERE "
                "deployment_namespace=%s AND task_id=%s",
                ("1" * 64, ns, child_id),
            )
        else:
            connection.execute(
                "UPDATE agent_tasks SET active_segment_id=%s WHERE "
                "deployment_namespace=%s AND task_id=%s",
                (setup[2].parent_task_id, ns, child_id),
            )
        return BudgetUsageReceipt(
            child_task_ref=str(child_id), model_tokens=1, tool_calls=1, runtime_seconds=1
        )

    with pytest.raises(OrchestrationToolError, match="usage_conflict"):
        _service(setup, usage_reader=reader).settle(key)
    assert _service(setup).observe(key)["usage"] is None


def test_stop_race_after_last_check_still_prevents_child_lease(setup):
    from contextlib import contextmanager

    run, _ = _run(setup)

    class RacingStop(PostgresOrchestrationAdmission):
        phases = 0

        @contextmanager
        def _phase(self, *, active):
            self.phases += 1
            phase = self.phases
            with super()._phase(active=active) as value:
                yield value
                if phase == 3:
                    _stop(setup)  # independent commit AFTER the last admission check

    child = _service(setup, RacingStop).request_task(run_ref=run, node_key="a")
    from agent_core.domain.leases import LeaseConflictError

    dsn, ns, _ = setup
    with psycopg.connect(dsn) as connection, pytest.raises(LeaseConflictError, match="stop"):
        acquire_lease_in_transaction(
            connection,
            ns,
            UUID(child.child_task_id),
            owner_instance_id="worker",
            ttl=timedelta(seconds=10),
        )


def test_default_missing_executor_budget_guard_refuses_even_valid_child(setup):
    run, _ = _run(setup)
    with pytest.raises(OrchestrationToolError, match="executor_budget_unavailable"):
        _service(setup, executor_budget_ready=None).request_task(run_ref=run, node_key="a")
    assert _count(setup, "orchestration_admission_originals") == 0
    assert _count(setup, "agent_tasks") == 1


@pytest.mark.parametrize("reduced_approval", [False, True])
def test_phase_two_uses_own_reservation_not_a_second_free_budget(setup, reduced_approval):
    run, key = _run(setup, tokens=100)
    dsn, ns, base = setup
    phases = [0]

    def authorize(action):
        phases[0] += 1
        with PostgresDatabase(dsn, deployment_namespace=ns).connect() as connection:
            rows = connection.execute(
                "SELECT reservation FROM orchestration_admission_originals "
                "WHERE deployment_namespace=%s AND parent_task_id=%s",
                (ns, base.parent_task_id),
            ).fetchall()
        approved = base.approved_budget
        if reduced_approval and phases[0] >= 3:
            approved = approved.model_copy(update={"model_tokens": 50})
        values = {
            name: max(0, getattr(approved, name) - sum(row["reservation"][name] for row in rows))
            for name in ("model_tokens", "tool_calls", "runtime_seconds")
        }
        return nullcontext(
            replace(
                base,
                approved_budget=approved,
                validation=replace(
                    base.validation,
                    parent_remaining_budget=BudgetReservation(**values),
                ),
            )
        )

    service = PostgresOrchestrationAdmission(
        dsn,
        deployment_namespace=ns,
        authorize=authorize,
        build_child=_build,
        executor_budget_ready=lambda authority, node: True,
    )
    if reduced_approval:
        with pytest.raises(OrchestrationToolError, match="budget_beyond_parent"):
            service.request_task(run_ref=run, node_key="a")
        assert service.observe(key)["state"] == "prepared"
        assert _count(setup, "agent_tasks") == 1
    else:
        result = service.request_task(run_ref=run, node_key="a")
        assert service.observe(key)["receipt"]["child_task_id"] == result.child_task_id
        assert _count(setup, "agent_tasks") == 2


def test_held_child_payload_cannot_drift_between_prepare_and_admit(setup):
    run, key = _run(setup)

    class ChangedInput(PostgresOrchestrationAdmission):
        def _execute(self, key, prepared):
            prepared.admission.events[2].payload["max_tool_calls"] = 99
            return super()._execute(key, prepared)

    with pytest.raises(OrchestrationToolError, match="original_conflict"):
        _service(setup, ChangedInput).request_task(run_ref=run, node_key="a")
    assert _count(setup, "agent_tasks") == 1
    assert _service(setup).observe(key)["state"] == "prepared"
