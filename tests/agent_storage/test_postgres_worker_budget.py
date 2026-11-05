"""Real ordinary Worker Task budget; no provider or disposable execution environment."""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from multiprocessing import get_context
from uuid import uuid4

import psycopg
import pytest
from agent_core.ports.worker_budget import ModelRequestBudget, WorkerBudgetError
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import acquire_lease_in_transaction
from agent_storage.postgres.worker_budget import PostgresWorkerBudgetStore

from tests.agent_storage.test_postgres_orchestration_admission import dsn as shared_dsn
from tests.agent_storage.test_postgres_orchestration_admission import setup as shared_setup

dsn, setup = shared_dsn, shared_setup


def started(setup):
    from agent_core.ports.worker_budget import WorkerBudgetBinding

    uri, ns, authority = setup
    database = PostgresDatabase(uri, deployment_namespace=ns)
    with database.connect() as connection:
        lease = acquire_lease_in_transaction(
            connection,
            ns,
            authority.parent_task_id,
            owner_instance_id="budget-test",
            ttl=timedelta(seconds=120),
        )
    binding = WorkerBudgetBinding(
        task_id=str(authority.parent_task_id),
        session_id=authority.parent_task_id,
        binding_digest=authority.parent_binding_digest,
        fence=lease.fence,
        attempt_number=1,
        max_model_tokens=100,
        max_runtime_seconds=60,
        max_tool_calls=2,
    )
    store = PostgresWorkerBudgetStore(uri, deployment_namespace=ns)
    store.start(binding)
    return store, binding, database


def request(tokens=60):
    body = b'{"model":"fixture"}'
    return ModelRequestBudget(body, sha256(body).hexdigest(), tokens - 10, 10, "fixture-known/1")


def _reserve_process(uri, ns, binding, queue):
    try:
        PostgresWorkerBudgetStore(uri, deployment_namespace=ns).reserve_model(binding, request())
        queue.put("reserved")
    except WorkerBudgetError:
        queue.put("refused")


def test_task_key_unknown_survives_attempt_and_restart(setup):
    store, binding, database = started(setup)
    first = store.reserve_model(binding, request())
    next_attempt = replace(binding, attempt_number=2)
    restarted = PostgresWorkerBudgetStore(database._dsn, deployment_namespace=store.namespace)
    restarted.start(next_attempt)
    with pytest.raises(WorkerBudgetError, match="unknown original"):
        restarted.reserve_model(next_attempt, request())
    with database.connect() as c:
        assert restarted.free_budget(c, binding.task_id).model_tokens == 40
    # Bad/missing provider usage cannot refund even one token.
    for usage in (None, {}, {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2}):
        with pytest.raises(WorkerBudgetError):
            store.settle_model(binding, first, usage, "provider-1")
    with database.connect() as c:
        assert store.free_budget(c, binding.task_id).model_tokens == 40
        assert store.usage_reader(c, binding.task_id) is None


def test_exact_receipt_idempotent_conflict_and_new_send_charge(setup, monkeypatch):
    store, binding, database = started(setup)
    statements = []
    execute = psycopg.Connection.execute

    def trace(connection, query, *args, **kwargs):
        if isinstance(query, str) and any(marker in query for marker in (
            "lock_timeout", "statement_timeout", "INSERT INTO worker_model_reservations",
            "UPDATE worker_model_reservations", "UPDATE worker_task_budgets",
        )):
            statements.append(query)
        return execute(connection, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", trace)
    first = store.reserve_model(binding, request())
    assert len(statements) == 2
    statements.clear()
    usage = {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
    store.settle_model(binding, first, usage, "provider-1")
    assert len(statements) == 2
    statements.clear()
    store.settle_model(binding, first, usage, "provider-1")
    assert len(statements) == 1
    with pytest.raises(WorkerBudgetError, match="receipt conflict"):
        store.settle_model(binding, first, usage, "provider-other")
    next_binding = replace(binding, attempt_number=2)
    store.start(next_binding)
    second = store.reserve_model(next_binding, request())
    assert second.reservation_id != first.reservation_id
    with database.connect() as c:
        assert store.free_budget(c, binding.task_id).model_tokens == 25


def test_cross_process_unique_unknown_original(setup):
    store, binding, database = started(setup)
    context = get_context("spawn")
    queue = context.Queue()
    jobs = [
        context.Process(
            target=_reserve_process, args=(database._dsn, store.namespace, binding, queue)
        )
        for _ in range(2)
    ]
    for job in jobs:
        job.start()
    for job in jobs:
        job.join(20)
        assert job.exitcode == 0
    assert sorted(queue.get(timeout=2) for _ in jobs) == ["refused", "reserved"]


def test_tool_uuid_and_absolute_deadline_never_reset(setup):
    store, binding, database = started(setup)
    call = str(uuid4())
    store.reserve_tool(binding, call)
    binding = replace(binding, attempt_number=2)
    store.start(binding)
    store.reserve_tool(binding, call)
    store.reserve_tool(binding, str(uuid4()))
    with pytest.raises(WorkerBudgetError, match="tool ceiling"):
        store.reserve_tool(binding, str(uuid4()))
    with database.connect() as c:
        c.execute(
            "UPDATE worker_task_budgets SET deadline=clock_timestamp()-interval '1 second' "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (store.namespace, binding.task_id),
        )
    for operation in (
        lambda: store.check(binding),
        lambda: store.start(replace(binding, attempt_number=9)),
        lambda: store.reserve_model(binding, request()),
    ):
        with pytest.raises(WorkerBudgetError, match="deadline"):
            operation()


def _child_process(environment, binding, run, queue):
    from contextlib import contextmanager

    from agent_orchestration.application.orchestration_port import OrchestrationToolError
    from agent_storage.postgres.orchestration_admission import PostgresOrchestrationAdmission
    from agent_storage.postgres.work_unit import postgres_work_unit

    from tests.agent_storage.test_postgres_orchestration_admission import _build

    uri, ns, authority = environment
    database = PostgresDatabase(uri, deployment_namespace=ns)
    budgets = PostgresWorkerBudgetStore(uri, deployment_namespace=ns)

    @contextmanager
    def authorize(action):
        with postgres_work_unit(database), database.connect() as c:
            approved, free = budgets.current_authority(c, binding)
            yield replace(
                authority,
                approved_budget=approved,
                validation=replace(authority.validation, parent_remaining_budget=free),
            )

    service = PostgresOrchestrationAdmission(
        uri,
        deployment_namespace=ns,
        authorize=authorize,
        build_child=_build,
        executor_budget_ready=lambda authority, node: True,
    )
    try:
        service.request_task(run_ref=run, node_key="a")
        queue.put("reserved")
    except (WorkerBudgetError, OrchestrationToolError):
        queue.put("refused")


def test_parent_own_model_and_child_reservation_share_one_ceiling_across_processes(setup):
    from tests.agent_storage.test_postgres_orchestration_admission import _run

    store, binding, database = started(setup)
    # This fixture's node has three tools; give the parent a compatible cap before any use.
    with database.connect() as c:
        c.execute(
            "UPDATE worker_task_budgets SET max_tool_calls=20 WHERE deployment_namespace=%s "
            "AND task_id=%s",
            (store.namespace, binding.task_id),
        )
    binding = replace(binding, max_tool_calls=20)
    run, _ = _run(setup, tokens=60)
    context = get_context("spawn")
    queue = context.Queue()
    jobs = [
        context.Process(
            target=_reserve_process, args=(database._dsn, store.namespace, binding, queue)
        ),
        context.Process(target=_child_process, args=(setup, binding, run, queue)),
    ]
    for job in jobs:
        job.start()
    for job in jobs:
        job.join(20)
        assert job.exitcode == 0
    assert sorted(queue.get(timeout=2) for _ in jobs) == ["refused", "reserved"]
    with database.connect() as c:
        assert store.free_budget(c, binding.task_id).model_tokens == 40


def test_child_deadline_is_clamped_to_original_parent_and_recheck_tracks_narrowing(setup):
    from agent_core.ports.worker_budget import WorkerBudgetBinding
    from agent_storage.postgres.task_admission import load_task_binding

    from tests.agent_storage.test_postgres_orchestration_admission import _run, _service

    store, binding, database = started(setup)
    run, _ = _run(setup, tokens=60)
    child = _service(setup).request_task(run_ref=run, node_key="a").child_task_id
    from uuid import UUID

    child_id = UUID(child)
    with database.connect() as c:
        c.execute(
            "UPDATE worker_task_budgets SET deadline=clock_timestamp()+interval '3 seconds' "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (store.namespace, binding.task_id),
        )
        lease = acquire_lease_in_transaction(
            c,
            store.namespace,
            child_id,
            owner_instance_id="child-budget",
            ttl=timedelta(seconds=60),
        )
    frozen = load_task_binding(
        database._dsn, deployment_namespace=store.namespace, task_id=child_id
    )
    child_binding = WorkerBudgetBinding(
        task_id=child,
        session_id=child_id,
        binding_digest=frozen.binding_digest,
        fence=lease.fence,
        attempt_number=1,
        max_model_tokens=60,
        max_runtime_seconds=10,
        max_tool_calls=3,
    )
    store.start(child_binding)
    assert 0 < store.check(child_binding) <= 3

    from tests.stream_storage.telemetry import Telemetry, phase

    telemetry = Telemetry()
    with telemetry.installed(), phase("deadline"):
        store.check_deadline(child_binding)
    assert telemetry.calls["initial/deadline/sql:task"] == 1
    with pytest.raises(WorkerBudgetError, match="binding moved"):
        store.check_deadline(replace(child_binding, attempt_number=2))
    with database.connect() as c:
        c.execute(
            "UPDATE worker_task_budgets SET deadline=clock_timestamp()-interval '1 second' "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (store.namespace, binding.task_id),
        )
    with pytest.raises(WorkerBudgetError, match="deadline"):
        store.check(child_binding)
    with pytest.raises(WorkerBudgetError, match="deadline"):
        store.check_deadline(child_binding)


def test_zero_model_and_tool_budget_remain_zero_across_attempts(setup):
    from dataclasses import replace

    uri, ns, _ = setup
    store, binding, database = started(setup)
    zero = replace(binding, max_model_tokens=0, max_tool_calls=0)
    store.start(zero)
    for attempt in (1, 2):
        current = replace(zero, attempt_number=attempt)
        store.start(current)
        with pytest.raises(WorkerBudgetError, match="token ceiling"):
            store.reserve_model(current, request())
        with pytest.raises(WorkerBudgetError, match="tool ceiling"):
            store.reserve_tool(current, str(uuid4()))
        with database.connect() as c:
            free = store.free_budget(c, binding.task_id)
            assert free.model_tokens == free.tool_calls == 0


def test_settled_orchestration_child_cannot_reopen_old_reservation(setup):
    from uuid import UUID

    from agent_core.ports.worker_budget import WorkerBudgetBinding
    from agent_storage.postgres.task_admission import load_task_binding
    from psycopg.types.json import Jsonb

    from tests.agent_storage.test_postgres_orchestration_admission import _run, _service

    store, binding, database = started(setup)
    run, key = _run(setup, tokens=60)
    child = _service(setup).request_task(run_ref=run, node_key="a").child_task_id
    child_id = UUID(child)
    with database.connect() as c:
        lease = acquire_lease_in_transaction(
            c, store.namespace, child_id, owner_instance_id="old-child", ttl=timedelta(seconds=60)
        )
    frozen = load_task_binding(
        database._dsn, deployment_namespace=store.namespace, task_id=child_id
    )
    child_binding = WorkerBudgetBinding(
        task_id=child,
        session_id=child_id,
        binding_digest=frozen.binding_digest,
        fence=lease.fence,
        attempt_number=1,
        max_model_tokens=60,
        max_runtime_seconds=10,
        max_tool_calls=3,
    )
    store.start(child_binding)
    # Represents B's immutable, trusted terminal settlement. Reopening projection alone
    # must never renew the released child reservation or its Task deadline.
    with database.connect() as c:
        original = c.execute(
            "SELECT deadline FROM worker_task_budgets WHERE deployment_namespace=%s AND task_id=%s",
            (store.namespace, child_id),
        ).fetchone()
        c.execute(
            "UPDATE orchestration_admission_originals SET usage=%s "
            "WHERE deployment_namespace=%s AND original_key=%s",
            (
                Jsonb(
                    {
                        "child_task_ref": child,
                        "model_tokens": 5,
                        "tool_calls": 0,
                        "runtime_seconds": 1,
                    }
                ),
                store.namespace,
                key,
            ),
        )
        c.execute(
            "UPDATE session_projections SET status='running' WHERE "
            "deployment_namespace=%s AND session_id=%s",
            (store.namespace, child_id),
        )
    with pytest.raises(WorkerBudgetError, match="settled child"):
        store.start(replace(child_binding, attempt_number=2))
    with database.connect() as c:
        assert (
            c.execute(
                "SELECT deadline FROM worker_task_budgets WHERE "
                "deployment_namespace=%s AND task_id=%s",
                (store.namespace, child_id),
            ).fetchone()
            == original
        )


def test_delegation_without_original_budget_reservation_cannot_execute(setup):
    from uuid import UUID

    from agent_core.ports.worker_budget import WorkerBudgetBinding
    from agent_storage.postgres.task_admission import load_task_binding

    from tests.agent_storage.test_postgres_orchestration_admission import _run, _service

    store, _, database = started(setup)
    run, key = _run(setup, tokens=60)
    child = _service(setup).request_task(run_ref=run, node_key="a").child_task_id
    child_id = UUID(child)
    with database.connect() as c:
        lease = acquire_lease_in_transaction(
            c,
            store.namespace,
            child_id,
            owner_instance_id="legacy-child",
            ttl=timedelta(seconds=60),
        )
        c.execute(
            "DELETE FROM orchestration_admission_originals WHERE deployment_namespace=%s "
            "AND original_key=%s",
            (store.namespace, key),
        )
    frozen = load_task_binding(
        database._dsn, deployment_namespace=store.namespace, task_id=child_id
    )
    binding = WorkerBudgetBinding(
        task_id=child,
        session_id=child_id,
        binding_digest=frozen.binding_digest,
        fence=lease.fence,
        attempt_number=1,
        max_model_tokens=60,
        max_runtime_seconds=10,
        max_tool_calls=3,
    )
    with pytest.raises(WorkerBudgetError, match="parent budget reservation"):
        store.start(binding)
    with database.connect() as c:
        assert (
            c.execute(
                "SELECT 1 FROM worker_task_budgets WHERE deployment_namespace=%s AND task_id=%s",
                (store.namespace, child_id),
            ).fetchone()
            is None
        )


@pytest.mark.parametrize(
    "metadata,confirmed",
    [
        ({"execution_state": "unknown"}, False),
        ({"execution_state": "not_executed"}, True),
        ({"execution_state": "executed", "business_outcome": "unknown"}, False),
        ({"execution_state": "executed", "client_effect_deferred": True}, False),
    ],
)
def test_terminal_failed_task_requires_confirmed_tool_outcome(setup, metadata, confirmed):
    from datetime import UTC, datetime

    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_storage import PostgresEventStore, PostgresProjectionStore

    store, binding, database = started(setup)
    call_id = str(uuid4())
    store.reserve_tool(binding, call_id)
    events = PostgresEventStore(database._dsn, deployment_namespace=store.namespace)
    for kind, payload in (
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
        (
            EventType.TOOL_EXECUTION_FAILED,
            {
                "tool_call_id": call_id,
                "tool_name": "fixture",
                "status": "failed",
                "metadata": metadata,
            },
        ),
        (EventType.SESSION_FAILED, {"attempt_number": 1, "reason": "fixture failure"}),
    ):
        events.append(
            SessionEvent.create(
                session_id=binding.session_id,
                sequence=events.list_for_session(binding.session_id)[-1].sequence + 1,
                event_type=kind,
                actor=EventActor.HARNESS,
                payload=payload,
                created_at=datetime.now(UTC),
            )
        )
    PostgresProjectionStore(database._dsn, deployment_namespace=store.namespace).save_session(
        rebuild_session(events.list_for_session(binding.session_id))
    )
    with database.connect() as c:
        usage = store.usage_reader(c, binding.task_id)
    assert (usage is not None) is confirmed
    if confirmed:
        assert usage.tool_calls == 1 and usage.model_tokens == 0
    elif metadata == {"execution_state": "unknown"}:
        # A later authoritative no-effect reconciliation resolves the original UUID;
        # the earlier failed/unknown event alone did not refund its reservation.
        events.append(
            SessionEvent.create(
                session_id=binding.session_id,
                sequence=events.list_for_session(binding.session_id)[-1].sequence + 1,
                event_type=EventType.TOOL_EXECUTION_FAILED,
                actor=EventActor.TOOL,
                payload={
                    "tool_call_id": call_id,
                    "tool_name": "fixture",
                    "status": "failed",
                    "metadata": {"execution_state": "not_executed"},
                },
                created_at=datetime.now(UTC),
            )
        )
        PostgresProjectionStore(database._dsn, deployment_namespace=store.namespace).save_session(
            rebuild_session(events.list_for_session(binding.session_id))
        )
        with database.connect() as c:
            assert store.usage_reader(c, binding.task_id).tool_calls == 1
