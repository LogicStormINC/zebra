"""Exact-fence worker boundary attribution and atomic derived receipt updates."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.session_projection import apply_event, rebuild_session
from agent_core.application.workspace_projection import apply_event as apply_workspace
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseLostError
from agent_core.ports import WorkerMutationAuthority
from agent_storage import (
    PostgresLeaseStore,
    PostgresProjectionStore,
    PostgresWorkspaceProjectionStore,
)
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus
from agent_storage.postgres.command_wakeup_receipts import HANDLED_EVENTS
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import assert_current_lease_fence
from psycopg.rows import dict_row

from tests.agent_storage.test_command_wakeup import _command
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _postgres_dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup_handoff import _handoff, _prepare
from tests.agent_storage.test_postgres_lease_clock import _wait, _wait_locked, _worker_dsn
from tests.agent_storage.test_postgres_leases import _expire

dsn = _dsn_fixture
postgres_dsn = _postgres_dsn_fixture


def _projections(dsn):
    return (
        PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE),
        PostgresWorkspaceProjectionStore(dsn, deployment_namespace=NAMESPACE),
    )


def _refresh(dsn, session_id):
    events = _store(dsn).list_for_session(session_id)
    sessions, workspaces = _projections(dsn)
    sessions.save_session(rebuild_session(events))
    workspaces.save_workspace(rebuild_workspace(events))


def _setup(dsn):
    command = _prepare(dsn)
    lease = _handoff(dsn, command).lease
    assert lease is not None
    _refresh(dsn, command.session_id)
    return command, lease


def _event(dsn, session_id, kind, payload=None):
    session = _projections(dsn)[0].get_session(session_id)
    if kind is EventType.SESSION_SUSPENDED:
        payload = {"reason": "tool_call_budget_exhausted", **(payload or {})}
    elif kind is EventType.CLARIFICATION_REQUESTED:
        payload = {
            "attempt_number": 1,
            "clarification_id": str(uuid4()),
            "tool_call_id": "clarify-1",
            "question": "Which audience?",
            "assistant_message": "Please choose the audience.",
            "conversation": [],
            "model_calls_used": 1,
            "tool_calls_executed": 0,
            **(payload or {}),
        }
    return SessionEvent.create(
        session_id=session_id,
        sequence=session.current_sequence + 1,
        event_type=kind,
        actor=EventActor.HARNESS,
        payload=payload or {},
        idempotency_key=str(uuid4()),
    )


def _commit(dsn, event, lease, *, persisted=False):
    sessions, workspaces = _projections(dsn)
    session = sessions.get_session(event.session_id)
    workspace = workspaces.get_workspace(event.session_id)
    authority = WorkerMutationAuthority(
        deployment_namespace=NAMESPACE,
        session_id=event.session_id,
        lease_fence=lease.fence,
        expected_stream_revision=event.sequence - 1,
    )
    method = (
        workspaces.project_persisted_worker_event if persisted else workspaces.commit_worker_event
    )
    return method(
        event, apply_event(session, event), apply_workspace(workspace, event), authority=authority
    )


def _receipt(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        return connection.execute(
            "SELECT * FROM command_handoff_receipts ORDER BY created_at"
        ).fetchone()


def _start(dsn, command, lease):
    event = _event(
        dsn, command.session_id, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}
    )
    _commit(dsn, event, lease)
    return event


@pytest.mark.parametrize("kind", sorted(HANDLED_EVENTS))
def test_explicit_durable_boundaries_are_bound_to_exact_started_event(dsn, kind):
    command, lease = _setup(dsn)
    started = _start(dsn, command, lease)
    payload = (
        {"turn_id": "legacy-turn:0", "turn_index": 0} if kind.value.startswith("turn_") else {}
    )
    terminal = _event(dsn, command.session_id, kind, payload)
    _commit(dsn, terminal, lease)
    row = _receipt(dsn)
    assert row["started_event_id"] == started.event_id
    assert row["handled_event_id"] == terminal.event_id
    assert row["turn_id"] == payload.get("turn_id")
    assert row["execution_floor_sequence"] == command.sequence
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT status FROM session_command_pending").fetchone() == (
            "done",
        )


def test_model_output_and_missing_started_boundary_do_not_complete_command(dsn):
    command, lease = _setup(dsn)
    model = _event(
        dsn,
        command.session_id,
        EventType.MODEL_RESPONSE_RECEIVED,
        {"assistant_message": "not sufficient"},
    )
    _commit(dsn, model, lease)
    terminal = _event(dsn, command.session_id, EventType.SESSION_SUSPENDED)
    _commit(dsn, terminal, lease)
    assert _receipt(dsn)["started_event_id"] is None
    assert _receipt(dsn)["handled_event_id"] is None
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT status FROM session_command_pending").fetchone() == (
            "pending",
        )


@pytest.mark.parametrize("failure", ["receipt", "pending"])
def test_receipt_failure_rolls_back_event_projections_and_pending(dsn, failure):
    command, lease = _setup(dsn)
    _start(dsn, command, lease)
    sessions, workspaces = _projections(dsn)
    before = sessions.get_session(command.session_id), workspaces.get_workspace(command.session_id)
    with psycopg.connect(dsn) as connection:
        statement = (
            "ALTER TABLE command_handoff_receipts ADD CONSTRAINT reject_test "
            "CHECK(handled_event_id IS NULL)"
            if failure == "receipt"
            else (
                "ALTER TABLE session_command_pending ADD CONSTRAINT reject_test "
                "CHECK(status='pending')"
            )
        )
        connection.execute(statement)
    terminal = _event(dsn, command.session_id, EventType.SESSION_SUSPENDED)
    with pytest.raises(psycopg.errors.CheckViolation):
        _commit(dsn, terminal, lease)
    assert (
        sessions.get_session(command.session_id),
        workspaces.get_workspace(command.session_id),
    ) == before
    assert terminal not in _store(dsn).list_for_session(command.session_id)
    assert _receipt(dsn)["handled_event_id"] is None


def test_canonical_already_projected_replay_repairs_only_exact_ids(dsn):
    command, lease = _setup(dsn)
    started = _start(dsn, command, lease)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_handoff_receipts SET started_event_id = NULL")
    _commit(dsn, started, lease)
    assert _receipt(dsn)["started_event_id"] == started.event_id
    pause = _event(dsn, command.session_id, EventType.APPROVAL_REQUESTED)
    _commit(dsn, pause, lease)
    _commit(dsn, pause, lease)
    later = _event(dsn, command.session_id, EventType.SESSION_CANCELLED)
    _commit(dsn, later, lease)
    assert _receipt(dsn)["handled_event_id"] == pause.event_id


def test_current_successor_fence_cannot_attribute_old_handoff(dsn):
    command, first = _setup(dsn)
    leases = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    leases.release(command.session_id, fence=first.fence)
    second = leases.acquire(
        command.session_id, owner_instance_id="successor", ttl=timedelta(seconds=30)
    )
    start = _event(dsn, command.session_id, EventType.HARNESS_ATTEMPT_STARTED)
    with pytest.raises(LeaseLostError):
        _commit(dsn, start, first)
    _commit(dsn, start, second)
    _commit(dsn, _event(dsn, command.session_id, EventType.SESSION_SUSPENDED), second)
    assert _receipt(dsn)["started_event_id"] is None
    assert _receipt(dsn)["handled_event_id"] is None


def test_old_start_above_accepted_but_at_floor_is_not_attributed(dsn):
    command = _prepare(dsn)
    old = _command(command.session_id)  # Reuse only an identifier factory, not its command payload.
    old_start = SessionEvent.create(
        session_id=command.session_id,
        sequence=command.sequence + 1,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
        idempotency_key=str(old.event_id),
    )
    _store(dsn).append(old_start)
    _refresh(dsn, command.session_id)
    lease = _handoff(dsn, command).lease
    assert lease is not None
    _commit(dsn, old_start, lease)
    assert _receipt(dsn)["started_event_id"] is None
    fresh = _start(dsn, command, lease)
    assert fresh.sequence > old_start.sequence
    assert _receipt(dsn)["started_event_id"] == fresh.event_id


def test_null_floor_legacy_receipt_never_gains_new_attribution(dsn):
    command, lease = _setup(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_handoff_receipts SET execution_floor_sequence = NULL")
    _start(dsn, command, lease)
    _commit(dsn, _event(dsn, command.session_id, EventType.SESSION_SUSPENDED), lease)
    assert _receipt(dsn)["started_event_id"] is None
    assert _receipt(dsn)["handled_event_id"] is None


def test_exact_companion_event_reconciliation_is_explicitly_not_atomic_with_original_event(dsn):
    command, lease = _setup(dsn)
    _start(dsn, command, lease)
    terminal = _event(dsn, command.session_id, EventType.SESSION_SUSPENDED)
    _store(dsn).append(terminal)  # Represents the already-committed companion transaction.
    assert _receipt(dsn)["handled_event_id"] is None
    _commit(dsn, terminal, lease, persisted=True)
    assert _receipt(dsn)["handled_event_id"] == terminal.event_id


def test_exact_handled_predecessor_unblocks_next_command_not_projection_revision(dsn):
    command, lease = _setup(dsn)
    _start(dsn, command, lease)
    pause = _event(dsn, command.session_id, EventType.APPROVAL_REQUESTED)
    _commit(dsn, pause, lease)
    later = _command(command.session_id, sequence=pause.sequence + 1, key="next")
    _store(dsn).append(later)
    _expire(dsn, NAMESPACE, command.session_id)
    assert _handoff(dsn, later).status is HandoffStatus.ACCEPTED


def test_historical_origin_does_not_gain_execution_attribution(dsn):
    command, lease = _setup(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_command_pending SET origin = 'historical'")
    _start(dsn, command, lease)
    _commit(dsn, _event(dsn, command.session_id, EventType.SESSION_SUSPENDED), lease)
    assert _receipt(dsn)["started_event_id"] is None
    assert _receipt(dsn)["handled_event_id"] is None


def test_handoff_does_not_lock_pending_while_waiting_for_worker_lease(dsn):
    command = _prepare(dsn)
    leases = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    old = leases.acquire(command.session_id, owner_instance_id="old", ttl=timedelta(seconds=2))
    name = f"receipt-lock-order-{uuid4()}"
    with ThreadPoolExecutor(max_workers=1) as executor:
        with psycopg.connect(dsn, autocommit=True) as observer:
            with PostgresDatabase(dsn, deployment_namespace=NAMESPACE).connect() as worker:
                assert_current_lease_fence(worker, NAMESPACE, command.session_id, old.fence)
                future = executor.submit(_handoff, _worker_dsn(dsn, name), command)
                _wait_locked(observer, name)
                # The worker holds lease SHARE; its later pending-row write must
                # not deadlock with handoff waiting for lease UPDATE.
                worker.execute("SET LOCAL lock_timeout = '500ms'")
                worker.execute("UPDATE session_command_pending SET status = status")
                _wait(observer, "SELECT clock_timestamp() > %s", (old.expires_at,))
            assert future.result(timeout=3).status is HandoffStatus.ACCEPTED
