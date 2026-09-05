"""Independent control commits, fence revocation and durable cleanup obligations."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from agent_core.application import current_turn
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.sessions import SessionStatus
from agent_core.ports import WorkerMutationAuthority
from agent_storage import PostgresLeaseStore, PostgresProjectionStore
from agent_storage.postgres.command_rollout import set_command_scope_rollout
from agent_storage.postgres.command_wakeup import _canonical_json, command_scope_key
from agent_storage.postgres.command_wakeup_control import ControlStatus, handle_control_command
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus
from agent_storage.postgres.command_wakeup_receipts import record_worker_command_boundary
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.leases import assert_current_lease_fence
from agent_storage.postgres.projections import save_session_in_transaction
from agent_storage.postgres.workspaces import save_workspace_in_transaction
from psycopg import sql

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_discovery import SCOPE
from tests.agent_storage.test_postgres_command_wakeup_handoff import _handoff, _prepare
from tests.agent_storage.test_postgres_command_wakeup_receipts import (
    _commit,
    _event,
    _refresh,
    _start,
)
from tests.agent_storage.test_postgres_command_wakeup_recovery import _rows
from tests.agent_storage.test_postgres_lease_clock import _wait_locked, _worker_dsn

dsn = _dsn_fixture
postgres_dsn = _pg_fixture


def _intent(dsn, session_id, kind):
    sequence = _store(dsn).list_for_session(session_id)[-1].sequence + 1
    command = SessionCommand(
        session_id=session_id,
        kind=SessionCommandKind(kind),
        expected_revision=sequence - 1,
        idempotency_key=str(uuid4()),
    )
    return _store(dsn).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=sequence,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.USER,
            payload=command.event_payload(),
            idempotency_key=command.idempotency_key,
        )
    )


def _control(dsn, command, **kwargs):
    return handle_control_command(
        dsn,
        deployment_namespace=NAMESPACE,
        scope=SCOPE,
        accepted_event_id=command.event_id,
        **kwargs,
    )


def _body(dsn, command):
    row = next(
        row
        for row in _rows(dsn, "broker_outbox")
        if str(row["operation_id"]) == command.payload["command_id"]
    )
    return _canonical_json(row["envelope_json"]).encode()


@pytest.mark.parametrize("kind", ["cancel", "stop"])
def test_control_bypasses_running_predecessor_revokes_and_records_cleanup(dsn, kind):
    original = _prepare(dsn)
    lease = _handoff(dsn, original).lease
    _refresh(dsn, original.session_id)
    _start(dsn, original, lease)
    command = _intent(dsn, original.session_id, kind)
    prior_receipts = _rows(dsn, "command_handoff_receipts")
    result = _control(dsn, command)
    assert result.status is ControlStatus.CANCELLED
    events = _store(dsn).list_for_session(original.session_id)
    assert [event.event_type for event in events[-2:]] == [
        EventType.TURN_CANCELLED,
        EventType.SESSION_CANCELLED,
    ]
    assert current_turn(events) is None
    assert events[-1].event_id == result.terminal_event_id
    assert _rows(dsn, "command_handoff_receipts") == prior_receipts
    old = next(
        row
        for row in _rows(dsn, "session_command_pending")
        if row["accepted_event_id"] == original.event_id
    )
    assert old["status"] == "cancelled" and old["cancelled_by_control_id"] == command.event_id
    receipt = _rows(dsn, "command_control_receipts")[0]
    assert (receipt["revoked_epoch"], receipt["revoked_token"], receipt["revoked_owner"]) == (
        lease.fence.control_plane_epoch,
        lease.fence.fencing_token,
        lease.fence.owner_instance_id,
    )
    assert _rows(dsn, "command_runtime_cleanup")[0]["status"] == "pending"
    leases = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    assert leases.get(original.session_id) is None
    with pytest.raises(LeaseLostError):
        leases.heartbeat(
            original.session_id, fence=lease.fence, ttl=timedelta(seconds=30), checkpoint=0
        )
    with pytest.raises(LeaseLostError):
        _commit(dsn, _event(dsn, original.session_id, EventType.MODEL_RESPONSE_RECEIVED), lease)


def test_broker_fallback_duplicate_keeps_one_outcome_and_cleanup(dsn):
    original = _prepare(dsn)
    _handoff(dsn, original)
    command = _intent(dsn, original.session_id, "cancel")
    body = _body(dsn, command)
    barrier = Barrier(2)

    def invoke(raw):
        barrier.wait(timeout=3)
        return _control(dsn, command, raw_body=raw)

    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = executor.submit(invoke, body), executor.submit(invoke, None)
        results = a.result(timeout=8), b.result(timeout=8)
    assert {result.status for result in results} == {
        ControlStatus.CANCELLED,
        ControlStatus.DUPLICATE,
    }
    assert len(_rows(dsn, "command_control_receipts")) == 1
    assert len(_rows(dsn, "broker_control_inbox")) == 1
    cleanup = _rows(dsn, "command_runtime_cleanup")
    assert len(cleanup) == 1
    assert _control(dsn, command).status is ControlStatus.DUPLICATE
    assert _rows(dsn, "command_runtime_cleanup") == cleanup


def test_control_mode_flip_is_rechecked_inside_scope_lock(dsn):
    original = _prepare(dsn)
    command = _intent(dsn, original.session_id, "cancel")
    scope_key = command_scope_key(SCOPE)
    set_command_scope_rollout(
        dsn,
        deployment_namespace=NAMESPACE,
        scope_key=scope_key,
        mode="broker",
        actor="operator",
        reason="control race acceptance",
    )
    before = _store(dsn).list_for_session(original.session_id)
    with psycopg.connect(dsn) as blocker, ThreadPoolExecutor(1) as pool:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,50))",
            (f"{NAMESPACE}:command-rollout:{scope_key}",),
        )
        pending = pool.submit(_control, dsn, command, required_scope_mode="broker")
        blocker.execute(
            """UPDATE command_delivery_scope_rollouts SET mode='shadow'
               WHERE deployment_namespace=%s AND scope_key=%s""",
            (NAMESPACE, scope_key),
        )
        blocker.commit()
        result = pending.result(2)
    assert result.status is ControlStatus.SCOPE_DEFERRED
    assert _store(dsn).list_for_session(original.session_id) == before
    assert not _rows(dsn, "command_control_receipts")
    assert not _rows(dsn, "command_runtime_cleanup")


@pytest.mark.parametrize(
    "table", ["command_control_receipts", "broker_control_inbox", "command_runtime_cleanup"]
)
def test_control_failure_rolls_back_events_projection_revocation_and_pending(dsn, table):
    original = _prepare(dsn)
    _handoff(dsn, original)
    command = _intent(dsn, original.session_id, "stop")
    names = (
        "session_events",
        "session_projections",
        "workspace_projections",
        "worker_leases",
        "session_command_pending",
        "command_handoff_receipts",
    )
    before = {name: _rows(dsn, name) for name in names}
    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL("ALTER TABLE {} ADD CONSTRAINT reject_test CHECK(false)").format(
                sql.Identifier(table)
            )
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        _control(dsn, command)
    assert before == {name: _rows(dsn, name) for name in names}
    assert not _rows(dsn, "command_control_receipts")


def test_terminal_noop_cites_exact_event_and_does_not_add_cleanup(dsn):
    original = _prepare(dsn)
    first = _intent(dsn, original.session_id, "cancel")
    cancelled = _control(dsn, first)
    cleanup = _rows(dsn, "command_runtime_cleanup")
    second = _intent(dsn, original.session_id, "stop")
    before = _store(dsn).list_for_session(original.session_id)
    result = _control(dsn, second)
    assert result.status is ControlStatus.TERMINAL_NOOP
    assert result.terminal_event_id == cancelled.terminal_event_id
    assert _store(dsn).list_for_session(original.session_id) == before
    assert _rows(dsn, "command_runtime_cleanup") == cleanup


def test_suspend_is_durably_unsupported_without_touching_execution(dsn):
    original = _prepare(dsn)
    _handoff(dsn, original)
    command = _intent(dsn, original.session_id, "suspend")
    names = (
        "session_events",
        "session_projections",
        "workspace_projections",
        "worker_leases",
        "command_handoff_receipts",
    )
    before = {name: _rows(dsn, name) for name in names}
    result = _control(dsn, command)
    assert result.status is ControlStatus.UNSUPPORTED and result.terminal_event_id is None
    assert before == {name: _rows(dsn, name) for name in names}
    assert not _rows(dsn, "command_runtime_cleanup")
    assert _rows(dsn, "command_control_receipts")[0]["outcome"] == "unsupported"


def test_exact_unsupported_suspend_does_not_block_following_run(dsn):
    suspend = _prepare(dsn, kind="suspend")
    assert _control(dsn, suspend).status is ControlStatus.UNSUPPORTED
    run = _intent(dsn, suspend.session_id, "run")
    assert _handoff(dsn, run).status is HandoffStatus.ACCEPTED


def test_wrong_scope_does_not_touch_victim_control_or_lease(dsn):
    original = _prepare(dsn)
    _handoff(dsn, original)
    command = _intent(dsn, original.session_id, "cancel")
    names = ("session_events", "worker_leases", "session_command_pending")
    before = {name: _rows(dsn, name) for name in names}
    with pytest.raises(ValueError, match="scope"):
        handle_control_command(
            dsn,
            deployment_namespace=NAMESPACE,
            scope=SCOPE.model_copy(update={"workspace_id": "victim"}),
            accepted_event_id=command.event_id,
        )
    assert before == {name: _rows(dsn, name) for name in names}


@pytest.mark.parametrize(
    ("table", "field", "value"),
    [
        ("session_command_pending", "status", "done"),
        ("session_command_pending", "status", "cancelled"),
        ("session_command_pending", "status", "dead"),
        ("session_command_pending", "origin", "historical"),
        ("broker_outbox", "status", "dead"),
    ],
)
def test_ineligible_control_reconciles_without_execution_mutation(dsn, table, field, value):
    original = _prepare(dsn)
    lease = _handoff(dsn, original).lease
    command = _intent(dsn, original.session_id, "cancel")
    with psycopg.connect(dsn) as connection:
        key = "operation_id" if table == "broker_outbox" else "accepted_event_id"
        identity = command.payload["command_id"] if table == "broker_outbox" else command.event_id
        connection.execute(
            sql.SQL("UPDATE {} SET {}=%s WHERE deployment_namespace=%s AND {}=%s").format(
                sql.Identifier(table), sql.Identifier(field), sql.Identifier(key)
            ),
            (value, NAMESPACE, identity),
        )
    names = (
        "session_events",
        "session_projections",
        "workspace_projections",
        "worker_leases",
        "command_handoff_receipts",
        "broker_outbox",
    )
    before = {name: _rows(dsn, name) for name in names}
    result = _control(dsn, command)
    assert result.status is ControlStatus.REQUIRES_RECONCILIATION
    assert result.terminal_event_id is None
    assert before == {name: _rows(dsn, name) for name in names}
    assert not _rows(dsn, "command_runtime_cleanup")
    assert PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).get(original.session_id) == lease
    receipt = _rows(dsn, "command_control_receipts")[0]
    assert receipt["outcome"] == "requires_reconciliation"
    assert receipt["revoked_epoch"] is None and receipt["revoked_token"] is None
    pending = next(
        row
        for row in _rows(dsn, "session_command_pending")
        if row["accepted_event_id"] == command.event_id
    )
    assert pending["status"] == (
        value if field == "status" and table != "broker_outbox" else "dead"
    )


@pytest.mark.parametrize("field", ["wake_generation", "scope"])
def test_control_rejects_unapproved_generation_or_raw_scope_without_mutation(dsn, field):
    original = _prepare(dsn)
    _handoff(dsn, original)
    command = _intent(dsn, original.session_id, "cancel")
    body = json.loads(_body(dsn, command))
    if field == "scope":
        body["scope"]["workspace_id"] = "foreign"
    else:
        body["wake_generation"] = 1
    names = (
        "session_events",
        "worker_leases",
        "session_command_pending",
        "command_handoff_receipts",
        "command_control_receipts",
        "broker_control_inbox",
    )
    before = {name: _rows(dsn, name) for name in names}
    with pytest.raises(ValueError):
        _control(dsn, command, raw_body=_canonical_json(body).encode())
    assert before == {name: _rows(dsn, name) for name in names}
    assert not _rows(dsn, "command_runtime_cleanup")


def test_control_waits_for_worker_write_then_revokes_its_exact_fence(dsn):
    original = _prepare(dsn)
    lease = _handoff(dsn, original).lease
    command = _intent(dsn, original.session_id, "cancel")
    events = _store(dsn).list_for_session(original.session_id)
    started = SessionEvent.create(
        session_id=original.session_id,
        sequence=events[-1].sequence + 1,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
    )
    name = f"control-wait-{uuid4()}"
    with ThreadPoolExecutor(max_workers=1) as executor:
        with psycopg.connect(dsn, autocommit=True) as observer:
            with PostgresDatabase(dsn, deployment_namespace=NAMESPACE).connect() as worker:
                assert_current_lease_fence(worker, NAMESPACE, original.session_id, lease.fence)
                append_event_in_transaction(worker, NAMESPACE, started)
                save_session_in_transaction(worker, NAMESPACE, rebuild_session([*events, started]))
                save_workspace_in_transaction(
                    worker, NAMESPACE, rebuild_workspace([*events, started])
                )
                record_worker_command_boundary(
                    worker,
                    started,
                    WorkerMutationAuthority(
                        deployment_namespace=NAMESPACE,
                        session_id=original.session_id,
                        lease_fence=lease.fence,
                        expected_stream_revision=started.sequence - 1,
                    ),
                )
                future = executor.submit(_control, _worker_dsn(dsn, name), command)
                _wait_locked(observer, name)
            assert future.result(timeout=5).status is ControlStatus.CANCELLED
    projection = PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE)
    assert projection.get_session(original.session_id).status is SessionStatus.CANCELLED
    receipt = _rows(dsn, "command_handoff_receipts")[0]
    assert receipt["started_event_id"] == started.event_id and receipt["handled_event_id"] is None
