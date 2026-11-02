"""Real PostgreSQL completion observations; model/counter remain explicit fixtures."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.worker_budget import WorkerBudgetBinding
from agent_orchestration.application.orchestration_port import OrchestrationToolError
from agent_orchestration.application.orchestration_runtime import OrchestrationRuntime
from agent_orchestration.application.orchestration_scheduling import NodeOutcome
from agent_storage import PostgresCloudArtifactPayloadStore
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.leases import acquire_lease_in_transaction
from agent_storage.postgres.workspaces import PostgresWorkspaceProjectionStore
from zebra_agent_worker.orchestration_wakeup_hook import OrchestrationWakeupHook

from tests.worker.test_orchestration_factory import (
    TrustedFixtureGateway,
    _proposal,
    _runtime,
)
from tests.worker.test_orchestration_factory import native as shared_native

native = shared_native


class FixtureObjectStore:
    """In-memory external object service fixture; native metadata/producer are real."""

    def __init__(self):
        self.bytes = {}

    def put_if_absent(self, request):
        from agent_core.domain.artifact_objects import ArtifactObjectReceipt

        self.bytes[str(request.expectation.artifact_id)] = request.payload
        return ArtifactObjectReceipt(
            expectation=request.expectation,
            object_version="fixture-version-1",
            verified_at=datetime.now(UTC),
        )


@pytest.fixture
def terminal(native, monkeypatch, tmp_path, request):
    from agent_core.domain.cloud_scope import OpaqueAuthorityScope
    from agent_core.domain.execution_authority import ExecutionAuthorityResolutionRequest
    from agent_core.domain.tools import ToolCall
    from agent_core.harness.models import HarnessEventDraft
    from agent_runtime.workspace import LocalWorkspace
    from agent_storage import PostgresProjectionStore
    from agent_storage.postgres.model_tool_projections import PostgresModelToolProjectionStore
    from agent_storage.postgres_model_tool_compat import (
        PostgresModelCallProjectionAdapter,
        PostgresToolRunProjectionAdapter,
    )
    from agent_tools import FileReadTool
    from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver
    from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
    from zebra_agent_worker.model_call_index import ModelCallIndexer
    from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator
    from zebra_agent_worker.tool_run_index import ToolRunIndexer

    factory, _, _, _, _, role, _ = native
    monkeypatch.setenv(role.bound_version.runtime_assembly.provider_profile.api_key_env, "fixture")
    factory.model_request_budget_factory = lambda *_: TrustedFixtureGateway._counter
    runtime = _runtime(native)
    run = runtime.propose_plan(_proposal())
    child = runtime.request_task(run_ref=run.run_ref, node_key="inspect")
    with factory.database.connect() as c:
        row = c.execute(
            "SELECT t.active_segment_id,b.snapshot_json FROM agent_tasks t "
            "JOIN task_binding_snapshots b ON b.deployment_namespace=t.deployment_namespace "
            "AND b.task_id=t.task_id WHERE t.deployment_namespace=%s AND t.task_id=%s",
            (factory.namespace, child.child_task_id),
        ).fetchone()
        lease = acquire_lease_in_transaction(
            c,
            factory.namespace,
            row["active_segment_id"],
            owner_instance_id="gate-child",
            ttl=timedelta(seconds=60),
        )
    binding = TaskBindingSnapshot.model_validate(row["snapshot_json"])
    budget = WorkerBudgetBinding(
        child.child_task_id,
        row["active_segment_id"],
        binding.binding_digest,
        lease.fence,
        1,
        10,
        5,
        1,
    )
    factory.budgets.start(budget)
    call = str(uuid4())
    factory.budgets.reserve_tool(budget, call)
    variant = getattr(request, "param", None)
    if variant in {"unknown_child_model", "unknown_parent_model"}:
        from hashlib import sha256

        from agent_core.ports.worker_budget import ModelRequestBudget

        guarded = budget if variant == "unknown_child_model" else native[3].worker_budget.binding
        body = b'{"max_tokens":1}'
        factory.budgets.reserve_model(
            guarded,
            ModelRequestBudget(
                body,
                sha256(body).hexdigest(),
                2,
                1,
                "fixture-reservation-no-response/1",
            ),
        )
    events = PostgresEventStore(factory.database._dsn, deployment_namespace=factory.namespace)
    projections = PostgresWorkspaceProjectionStore(
        factory.database._dsn, deployment_namespace=factory.namespace
    )
    admitted = events.list_for_session(budget.session_id)
    authority = WorkerMutationAuthority(
        deployment_namespace=factory.namespace,
        session_id=budget.session_id,
        lease_fence=lease.fence,
        expected_stream_revision=admitted[-1].sequence - 1,
    )
    projections.project_persisted_worker_event(
        admitted[-1],
        rebuild_session(admitted),
        rebuild_workspace(admitted),
        authority=authority,
    )
    indexes = PostgresModelToolProjectionStore(
        factory.database._dsn, deployment_namespace=factory.namespace
    )
    recorder = DurableHarnessEventRecorder(
        session=rebuild_session(admitted),
        workspace=rebuild_workspace(admitted),
        event_store=events,
        projection_store=PostgresProjectionStore(
            factory.database._dsn, deployment_namespace=factory.namespace
        ),
        workspace_store=projections,
        worker_projection_transaction=projections,
        worker_mutation_authority=authority.model_copy(
            update={"expected_stream_revision": admitted[-1].sequence}
        ),
        model_call_indexer=ModelCallIndexer(PostgresModelCallProjectionAdapter(indexes)),
        tool_run_indexer=ToolRunIndexer(PostgresToolRunProjectionAdapter(indexes)),
    )
    objects = FixtureObjectStore()
    coordinator = CloudToolOutputArtifactCoordinator(
        budget.session_id,
        PostgresCloudArtifactPayloadStore(
            factory.database._dsn, deployment_namespace=factory.namespace
        ),
        objects,
    )
    proof = BoundHostExecutionAuthorityResolver(binding).resolve_for_attempt(
        ExecutionAuthorityResolutionRequest(
            session_id=budget.session_id,
            attempt_number=1,
            validated_at=datetime.now(UTC),
            scope=OpaqueAuthorityScope(
                authority_issuer=binding.host_capability.authority_issuer,
                namespace_id=binding.host_capability.namespace_id,
            ),
        )
    )
    for kind, payload in (
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
        (EventType.EXECUTION_AUTHORITY_RESOLVED, proof.model_dump(mode="json")),
        (
            EventType.TOOL_CALL_PROPOSED,
            {
                "attempt_number": 1,
                "tool_call_id": call,
                "tool_name": "files.read",
                "arguments": {"path": "evidence.txt"},
            },
        ),
        (
            EventType.TOOL_EXECUTION_STARTED,
            {"attempt_number": 1, "tool_call_id": call, "tool_name": "files.read"},
        ),
    ):
        coordinator.append_draft(HarnessEventDraft(kind, EventActor.HARNESS, payload), recorder)
    (tmp_path / "evidence.txt").write_text("actual FileReadTool evidence")
    result = FileReadTool(
        LocalWorkspace(tmp_path), output_projector=coordinator.output_projector
    ).handle(
        ToolCall(
            tool_call_id=call,
            name="files.read",
            arguments={"path": "evidence.txt"},
            created_at=datetime.now(UTC),
        )
    )
    coordinator.append_draft(
        HarnessEventDraft(
            EventType.TOOL_EXECUTION_COMPLETED,
            EventActor.TOOL,
            {
                "attempt_number": 1,
                "tool_name": "files.read",
                "tool_call_id": call,
                "status": result.status.value,
                "output": result.output,
                "metadata": result.metadata,
            },
        ),
        recorder,
    )
    recorder.append_draft(
        HarnessEventDraft(
            EventType.SESSION_COMPLETED,
            EventActor.HARNESS,
            {
                "summary": "model summary is not proof",
            },
        )
    )
    assert list(objects.bytes.values()) == [b"actual FileReadTool evidence"]
    runtime.complete_node(
        run.run_ref,
        "inspect",
        NodeOutcome.COMPLETED,
        revision=1,
        child_task_id=child.child_task_id,
    )
    return factory, runtime, run, child, budget


def _observations(factory, run):
    with factory.database.connect() as c:
        return c.execute(
            "SELECT * FROM orchestration_completion_observations "
            "WHERE deployment_namespace=%s AND run_id=%s ORDER BY created_at",
            (factory.namespace, run.run_ref),
        ).fetchall()


def test_real_tool_observation_is_immutable_idempotent_and_policy_refused(terminal):
    factory, runtime, run, child, _ = terminal
    for _ in range(2):
        with pytest.raises(OrchestrationToolError, match="gate_policy_unavailable"):
            runtime.synthesize(run.run_ref)
    rows = _observations(factory, run)
    assert len(rows) == 1
    facts = rows[0]["facts"]
    assert facts["children"][0]["child_task_id"] == child.child_task_id
    assert any(t["successful"] for t in facts["children"][0]["tools"])
    assert len(facts["children"][0]["artifacts"]) == 1
    assert facts["policy"] is None
    assert "model summary" not in str(facts)
    assert factory.store.read_run_status(run.run_ref) == "running"
    assert factory.store.read_completion_receipt(run.run_ref, 1, rows[0]["input_digest"])
    assert factory.store.read_completion_receipt(run.run_ref, 2, rows[0]["input_digest"]) is None
    import psycopg

    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with factory.database.connect() as c:
            c.execute(
                "UPDATE orchestration_completion_observations SET evaluation='{}' "
                "WHERE deployment_namespace=%s AND run_id=%s",
                (factory.namespace, run.run_ref),
            )


def test_recovery_retries_gate_after_usage_was_already_settled(terminal):
    factory, _, run, _, _ = terminal
    with factory.database.connect() as c:
        c.execute(
            "UPDATE orchestration_admission_originals SET usage=reservation "
            "WHERE deployment_namespace=%s AND run_id=%s",
            (factory.namespace, run.run_ref),
        )
    hook = OrchestrationWakeupHook(
        factory.database._dsn, deployment_namespace=factory.namespace, gate_store=factory.store
    )
    hook.reconcile_pending(limit=1)
    assert len(_observations(factory, run)) == 1
    assert factory.store.read_run_status(run.run_ref) == "running"


def test_current_lease_owner_change_cannot_produce_gate_receipt(terminal):
    factory, runtime, run, _, _ = terminal
    with factory.database.connect() as c:
        c.execute(
            "UPDATE worker_leases SET owner_instance_id='replacement' "
            "WHERE deployment_namespace=%s AND session_id=%s",
            (factory.namespace, native_parent(factory, run)),
        )
    from agent_core.domain.leases import LeaseLostError

    with pytest.raises(LeaseLostError):
        runtime.synthesize(run.run_ref)
    assert _observations(factory, run) == []
    assert factory.store.read_run_status(run.run_ref) == "running"


def native_parent(factory, run):
    return factory.store.get_snapshot(run.run_ref).parent_task_id


def test_legacy_passed_receipt_is_not_a_gate_producer(terminal):
    factory, _, run, child, _ = terminal
    factory.store.record_gate_receipt(
        child_task_id=child.child_task_id, gate_name="all", passed=True, reason_code="passed"
    )
    unconfigured = type(factory.store)(
        factory.database._dsn, deployment_namespace=factory.namespace
    )
    with pytest.raises(OrchestrationToolError, match="gate_authority_unavailable"):
        OrchestrationRuntime(unconfigured, require_persisted_gate=True).synthesize(run.run_ref)
    assert _observations(factory, run) == []


def test_changed_original_payload_cannot_reuse_an_observation(terminal):
    factory, runtime, run, _, _ = terminal
    with factory.database.connect() as c:
        c.execute(
            "UPDATE orchestration_admission_originals SET payload=payload||'{\"changed\":true}' "
            "WHERE deployment_namespace=%s AND run_id=%s",
            (factory.namespace, run.run_ref),
        )
    with pytest.raises(OrchestrationToolError, match="orchestration_original_conflict"):
        runtime.synthesize(run.run_ref)
    assert _observations(factory, run) == []


def test_fixture_only_pass_and_terminal_cas_rollback_are_atomic(terminal, monkeypatch):
    """Injected evaluator proves transaction mechanics, never production review success."""
    import psycopg
    from agent_orchestration.application.completion_gate import GateEvaluation
    from agent_storage.postgres import orchestration_gate
    from psycopg import sql

    factory, runtime, run, _, _ = terminal
    monkeypatch.setattr(
        orchestration_gate,
        "evaluate_durable_completion",
        lambda *a, **k: GateEvaluation((), True, False, "fixture_only_pass"),
    )
    function = "gate_failure_" + uuid4().hex
    with factory.database.connect() as c:
        c.execute(
            sql.SQL(
                "CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                "IF NEW.run_id={} AND NEW.deployment_namespace={} AND NEW.status='completed' "
                "THEN RAISE EXCEPTION 'fixture terminal write failed'; END IF; RETURN NEW; END $$"
            ).format(
                sql.Identifier(function), sql.Literal(run.run_ref), sql.Literal(factory.namespace)
            )
        )
        c.execute(
            sql.SQL(
                "CREATE TRIGGER {} BEFORE UPDATE ON orchestration_runs "
                "FOR EACH ROW EXECUTE FUNCTION {}()"
            ).format(sql.Identifier(function), sql.Identifier(function))
        )
    try:
        with pytest.raises(psycopg.errors.RaiseException, match="fixture terminal write failed"):
            runtime.synthesize(run.run_ref)
        assert _observations(factory, run) == []
        assert factory.store.read_run_status(run.run_ref) == "running"
    finally:
        with factory.database.connect() as c:
            c.execute(
                sql.SQL("DROP TRIGGER {} ON orchestration_runs").format(sql.Identifier(function))
            )
            c.execute(sql.SQL("DROP FUNCTION {}()").format(sql.Identifier(function)))
    runtime.synthesize(run.run_ref)
    runtime.synthesize(run.run_ref)
    assert factory.store.read_run_status(run.run_ref) == "completed"
    rows = _observations(factory, run)
    assert len(rows) == 1 and rows[0]["evaluation"]["reason_code"] == "fixture_only_pass"


@pytest.mark.parametrize(
    "native",
    [
        {
            "evaluation_profile_ref": "evaluation-profile/orchestration-readonly@1",
        }
    ],
    indirect=True,
)
def test_published_frozen_readonly_policy_completes_without_review_fixture(terminal):
    """Real policy/Registry/Worker events; provider counter/object receipt remain fixtures."""
    factory, runtime, run, _, _ = terminal
    runtime.synthesize(run.run_ref)
    runtime.synthesize(run.run_ref)
    assert factory.store.read_run_status(run.run_ref) == "completed"
    rows = _observations(factory, run)
    assert len(rows) == 1 and rows[0]["evaluation"]["passed"] is True
    assert rows[0]["facts"]["policy"]["semantics"]["review_required"] is False


def test_readonly_pairing_rejects_write_and_mismatched_path_without_database():
    from agent_storage.postgres.orchestration_gate_queries import readonly_tools

    call = "fixture-id"
    events = [
        {
            "event_id": "proposed",
            "event_type": "tool_call_proposed",
            "actor": "harness",
            "payload": {
                "tool_call_id": call,
                "tool_name": "files.read",
                "attempt_number": 1,
                "arguments": {"path": "evidence.txt"},
            },
        },
        {
            "event_id": "started",
            "event_type": "tool_execution_started",
            "actor": "harness",
            "payload": {"tool_call_id": call, "tool_name": "files.read", "attempt_number": 1},
        },
        {
            "event_id": "terminal",
            "event_type": "tool_execution_completed",
            "actor": "tool",
            "payload": {
                "tool_call_id": call,
                "tool_name": "files.read",
                "attempt_number": 1,
                "status": "executed",
                "metadata": {"path": "evidence.txt"},
            },
        },
    ]
    assert readonly_tools(events, {call}) == (True, {"terminal"})
    events[2]["actor"] = "harness"
    assert readonly_tools(events, {call}) == (False, set())
    events[2]["actor"] = "tool"
    events[2]["event_type"] = "tool_execution_failed"
    assert readonly_tools(events, {call}) == (False, set())
    events[2]["event_type"] = "tool_execution_completed"
    events[2]["payload"]["metadata"]["path"] = "different.txt"
    assert readonly_tools(events, {call}) == (False, set())
    events[2]["payload"]["tool_name"] = "files.write"
    assert readonly_tools(events, {call}) == (False, set())


@pytest.mark.parametrize("terminal", ["unknown_child_model", "unknown_parent_model"], indirect=True)
@pytest.mark.parametrize(
    "native",
    [
        {
            "evaluation_profile_ref": "evaluation-profile/orchestration-readonly@1",
        }
    ],
    indirect=True,
)
def test_actual_unknown_model_reservation_refuses_completion_without_refund(terminal):
    factory, runtime, run, _, _ = terminal
    with pytest.raises(OrchestrationToolError, match="gate_usage_unavailable"):
        runtime.synthesize(run.run_ref)
    assert _observations(factory, run) == []
    assert factory.store.read_run_status(run.run_ref) == "running"
    with factory.database.connect() as c:
        pending = c.execute(
            "SELECT count(*) AS n FROM worker_model_reservations "
            "WHERE deployment_namespace=%s AND receipt IS NULL",
            (factory.namespace,),
        ).fetchone()["n"]
    assert pending == 1


@pytest.mark.parametrize(
    "native",
    [
        {
            "evaluation_profile_ref": "evaluation-profile/orchestration-readonly@1",
        }
    ],
    indirect=True,
)
def test_native_stop_committed_after_prechecks_is_rejected_by_same_statement_cas(
    terminal, monkeypatch
):
    from uuid import UUID

    from agent_storage.postgres import orchestration_gate
    from agent_storage.postgres.force_stops import PostgresForceStops

    factory, runtime, run, _, _ = terminal
    original = orchestration_gate.complete_cas

    def stop_then_cas(c, ns, snapshot, parent, children):
        with factory.database.connect() as connection:
            binding_row = connection.execute(
                "SELECT snapshot_json FROM task_binding_snapshots "
                "WHERE deployment_namespace=%s AND task_id=%s "
                "ORDER BY binding_revision DESC LIMIT 1",
                (factory.namespace, str(snapshot.parent_task_id)),
            ).fetchone()
        binding = TaskBindingSnapshot.model_validate(binding_row["snapshot_json"])
        PostgresForceStops(factory.database._dsn, deployment_namespace=ns).request(
            UUID(str(snapshot.parent_task_id)),
            binding.host_capability.host_context,
            "late-gate-stop-" + uuid4().hex,
            authority_issuer=binding.host_capability.authority_issuer,
        )
        return original(c, ns, snapshot, parent, children)

    monkeypatch.setattr(orchestration_gate, "complete_cas", stop_then_cas)
    with pytest.raises(OrchestrationToolError, match="terminal CAS failed"):
        runtime.synthesize(run.run_ref)
    assert _observations(factory, run) == []
    assert factory.store.read_run_status(run.run_ref) == "running"


def _complete_process(dsn, namespace, run_ref, ready, results):
    from zebra_agent_worker.orchestration_composition import PostgresOrchestrationFactory

    ready.wait(15)
    try:
        factory = PostgresOrchestrationFactory(dsn, namespace)
        OrchestrationRuntime(factory.store, require_persisted_gate=True).synthesize(run_ref)
        results.put("completed")
    except Exception as error:
        results.put(type(error).__name__)


@pytest.mark.parametrize(
    "native",
    [
        {
            "evaluation_profile_ref": "evaluation-profile/orchestration-readonly@1",
        }
    ],
    indirect=True,
)
def test_two_spawn_processes_complete_the_same_real_policy_once(terminal):
    from multiprocessing import get_context

    factory, _, run, _, _ = terminal
    context = get_context("spawn")
    ready, results = context.Event(), context.Queue()
    jobs = [
        context.Process(
            target=_complete_process,
            args=(
                factory.database._dsn,
                factory.namespace,
                run.run_ref,
                ready,
                results,
            ),
        )
        for _ in range(2)
    ]
    try:
        for job in jobs:
            job.start()
        ready.set()
        for job in jobs:
            job.join(20)
            assert job.exitcode == 0
        assert [results.get(timeout=2) for _ in jobs] == ["completed", "completed"]
        assert len(_observations(factory, run)) == 1
        assert factory.store.read_run_status(run.run_ref) == "completed"
    finally:
        for job in jobs:
            if job.is_alive():
                job.terminate()
                job.join(5)


@pytest.mark.parametrize(
    "native",
    [
        {
            "evaluation_profile_ref": "evaluation-profile/orchestration-readonly@1",
        }
    ],
    indirect=True,
)
def test_artifact_expiring_after_prechecks_refuses_terminal_cas(terminal, monkeypatch):
    import time

    from agent_storage.postgres import orchestration_gate

    factory, runtime, run, _, _ = terminal
    with factory.database.connect() as c:
        c.execute(
            "UPDATE artifact_payload_metadata "
            "SET retained_until=clock_timestamp()+interval '1 second' "
            "WHERE deployment_namespace=%s",
            (factory.namespace,),
        )
    original = orchestration_gate.complete_cas

    def after_retention_deadline(*args):
        time.sleep(1.1)
        return original(*args)

    monkeypatch.setattr(orchestration_gate, "complete_cas", after_retention_deadline)
    with pytest.raises(OrchestrationToolError, match="terminal CAS failed"):
        runtime.synthesize(run.run_ref)
    assert _observations(factory, run) == []
    assert factory.store.read_run_status(run.run_ref) == "running"
