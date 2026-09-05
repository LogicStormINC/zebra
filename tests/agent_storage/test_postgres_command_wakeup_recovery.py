"""Real PG bounded recovery proof, generations, ambiguity and transaction boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage.postgres.command_wakeup import CommandAdmissionCapacityError, _canonical_json
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus
from agent_storage.postgres.command_wakeup_recovery import RecoveryStatus, recover_command_batch
from agent_storage.postgres.command_wakeup_relay import claim_relay_batch
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import lock_session_lease_boundary
from psycopg.rows import dict_row

from tests.agent_storage.test_command_wakeup import _command
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_discovery import SCOPE
from tests.agent_storage.test_postgres_command_wakeup_handoff import _handoff, _prepare
from tests.agent_storage.test_postgres_lease_clock import _wait, _wait_locked, _worker_dsn
from tests.agent_storage.test_postgres_leases import _expire

dsn = _dsn_fixture
postgres_dsn = _pg_fixture


def _due(dsn):
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_command_pending SET recovery_due_at = clock_timestamp() "
            "- interval '1 second'"
        )
        connection.execute(
            "UPDATE broker_outbox SET status = 'published', "
            "published_at = clock_timestamp() - interval '2 minutes'"
        )


def _recover(dsn, **kwargs):
    return recover_command_batch(dsn, deployment_namespace=NAMESPACE, scope=SCOPE, **kwargs)


def _rows(dsn, table):
    from psycopg import sql

    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        return connection.execute(
            sql.SQL("SELECT * FROM {}").format(sql.Identifier(table))
        ).fetchall()


def _body(dsn, generation):
    row = next(row for row in _rows(dsn, "broker_outbox") if row["wake_generation"] == generation)
    return _canonical_json(row["envelope_json"]).encode()


def test_published_no_handoff_new_identity_and_old_delivery_cannot_execute(dsn):
    command = _prepare(dsn)
    old = _body(dsn, 0)
    _due(dsn)
    assert _recover(dsn)[0].status is RecoveryStatus.APPROVED
    approval = _rows(dsn, "command_recovery_attempts")[0]
    assert approval["previous_receipt"] is None
    assert str(approval["message_id"]) != str(approval["previous_message_id"])
    assert _handoff(dsn, command, raw_body=old).status is HandoffStatus.DUPLICATE
    assert not _rows(dsn, "worker_leases")
    assert _handoff(dsn, command).status is HandoffStatus.ACCEPTED
    assert _handoff(dsn, command, raw_body=old).lease is None
    assert _rows(dsn, "command_handoff_receipts")[0]["wake_generation"] == 1


def test_recovery_respects_global_outbox_capacity(dsn):
    _prepare(dsn)
    _due(dsn)
    blocker = _seed(dsn, tenant="tenant-b")
    _store(dsn).append(_command(blocker.session_id, key="capacity-blocker"))
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """UPDATE command_wakeup_rollouts
               SET max_unpublished_outbox=1, reserved_control_outbox=0"""
        )
    with pytest.raises(CommandAdmissionCapacityError, match="command_outbox_capacity"):
        _recover(dsn)
    assert not _rows(dsn, "command_recovery_attempts")
    assert {row["wake_generation"] for row in _rows(dsn, "broker_outbox")} == {0}


def test_expired_unstarted_rebind_preserves_old_fence_floor_and_inbox(dsn):
    command = _prepare(dsn)
    original = _handoff(dsn, command)
    old_inbox = _rows(dsn, "broker_command_inbox")[0]
    _expire(dsn, NAMESPACE, command.session_id)
    _due(dsn)
    assert _recover(dsn)[0].status is RecoveryStatus.APPROVED
    previous = _rows(dsn, "command_recovery_attempts")[0]["previous_receipt"]
    assert previous["fencing_token"] == original.lease.fence.fencing_token
    assert previous["control_plane_epoch"] == str(original.lease.fence.control_plane_epoch)
    assert previous["execution_floor_sequence"] == command.sequence
    new = _handoff(dsn, command, raw_body=_body(dsn, 1))
    assert new.status is HandoffStatus.ACCEPTED
    assert new.lease.fence.fencing_token > original.lease.fence.fencing_token
    assert old_inbox in _rows(dsn, "broker_command_inbox")
    assert _handoff(dsn, command, raw_body=_body(dsn, 0)).lease is None


TAIL_CASES = [
    (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
    (EventType.MODEL_RESPONSE_RECEIVED, {"attempt_number": 1, "assistant_message": "uncertain"}),
    (EventType.TOOL_EXECUTION_STARTED, {"attempt_number": 1, "tool_name": "files.read"}),
    (EventType.SESSION_COMMAND_ACCEPTED, None),
]


@pytest.mark.parametrize("kind,payload", TAIL_CASES)
def test_tail_fixture_payload_contracts_without_database(kind, payload):
    command = _command()
    event = SessionEvent.create(
        session_id=command.session_id,
        sequence=4,
        event_type=kind,
        actor=EventActor.HARNESS,
        payload=command.payload if payload is None else payload,
    )
    assert event.event_type is kind and event.payload


@pytest.mark.parametrize("kind,payload", TAIL_CASES)
def test_any_raw_tail_evidence_even_without_started_receipt_is_quarantined(dsn, kind, payload):
    command = _prepare(dsn)
    _handoff(dsn, command)
    event = (
        _command(command.session_id, sequence=4, key="later")
        if payload is None
        else SessionEvent.create(
            session_id=command.session_id,
            sequence=4,
            event_type=kind,
            actor=EventActor.HARNESS,
            payload=payload,
        )
    )
    _store(dsn).append(event)
    _expire(dsn, NAMESPACE, command.session_id)
    _due(dsn)
    result = _recover(dsn)
    assert any(item.status is RecoveryStatus.REQUIRES_RECONCILIATION for item in result)
    original = next(
        row
        for row in _rows(dsn, "session_command_pending")
        if row["accepted_event_id"] == command.event_id
    )
    assert original["status"] == "dead" and original["current_generation"] == 0
    assert original["recovery_code"] == "requires_reconciliation"
    assert all(
        row["accepted_event_id"] != command.event_id
        for row in _rows(dsn, "command_recovery_attempts")
    )


def test_active_lease_defers_without_quarantining_and_batch_progresses(dsn):
    command = _prepare(dsn)
    _handoff(dsn, command)
    _due(dsn)
    assert _recover(dsn, batch_size=1)[0].status is RecoveryStatus.DEFERRED
    assert _recover(dsn, batch_size=1) == ()
    assert _rows(dsn, "session_command_pending")[0]["status"] == "pending"


def test_two_recovery_calls_approve_only_one_generation(dsn):
    _prepare(dsn)
    _due(dsn)
    barrier = Barrier(2)

    def recover():
        barrier.wait(timeout=3)
        return _recover(dsn)

    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = executor.submit(recover), executor.submit(recover)
        results = (*a.result(timeout=8), *b.result(timeout=8))
    assert sum(row.status is RecoveryStatus.APPROVED for row in results) == 1
    assert len(_rows(dsn, "broker_outbox")) == 2
    assert len(_rows(dsn, "command_recovery_attempts")) == 1


@pytest.mark.parametrize("first", ["fallback", "recovery"])
def test_fallback_and_recovery_advisory_queue_both_winners(dsn, first):
    command = _prepare(dsn)
    old_body = _body(dsn, 0)
    _due(dsn)
    names = {kind: f"{kind}-race-{uuid4()}" for kind in ("fallback", "recovery")}
    calls = {
        "fallback": lambda: _handoff(_worker_dsn(dsn, names["fallback"]), command),
        "recovery": lambda: _recover(_worker_dsn(dsn, names["recovery"])),
    }
    second = "recovery" if first == "fallback" else "fallback"
    with ThreadPoolExecutor(max_workers=2) as executor:
        with psycopg.connect(dsn, autocommit=True) as observer:
            with PostgresDatabase(dsn, deployment_namespace=NAMESPACE).connect() as blocker:
                lock_session_lease_boundary(blocker, NAMESPACE, command.session_id)
                first_future = executor.submit(calls[first])
                _wait_locked(observer, names[first])
                second_future = executor.submit(calls[second])
                _wait_locked(observer, names[second])
            results = {
                first: first_future.result(timeout=5),
                second: second_future.result(timeout=5),
            }
    assert results["fallback"].status is HandoffStatus.ACCEPTED
    expected = RecoveryStatus.DEFERRED if first == "fallback" else RecoveryStatus.APPROVED
    assert results["recovery"][0].status is expected
    generation = 0 if first == "fallback" else 1
    assert len(_rows(dsn, "worker_leases")) == 1
    assert len(_rows(dsn, "command_recovery_attempts")) == generation
    assert _rows(dsn, "session_command_pending")[0]["current_generation"] == generation
    assert _rows(dsn, "command_handoff_receipts")[0]["wake_generation"] == generation
    duplicate = _handoff(dsn, command, raw_body=old_body)
    assert duplicate.status is HandoffStatus.DUPLICATE and duplicate.lease is None


def test_approval_failure_rolls_back_generation_outbox_and_history(dsn):
    _prepare(dsn)
    _due(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "ALTER TABLE command_recovery_attempts ADD CONSTRAINT reject_test "
            "CHECK(wake_generation < 1)"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        _recover(dsn)
    assert len(_rows(dsn, "broker_outbox")) == 1
    assert not _rows(dsn, "command_recovery_attempts")
    assert _rows(dsn, "session_command_pending")[0]["current_generation"] == 0


@pytest.mark.parametrize("dead", [True, False])
@pytest.mark.parametrize("batch_size", [1, 16])
def test_poison_first_does_not_starve_healthy_candidate(dsn, dead, batch_size):
    poison = _prepare(dsn)
    healthy = _command(_seed(dsn).session_id)
    _store(dsn).append(healthy)
    _due(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_command_pending "
            "SET recovery_due_at=clock_timestamp()-interval '5 minutes' "
            "WHERE accepted_event_id=%s",
            (poison.event_id,),
        )
        connection.execute(
            "UPDATE broker_outbox SET envelope_json='{}'::jsonb, status=%s WHERE operation_id=%s",
            ("dead" if dead else "published", poison.payload["command_id"]),
        )
    events_before = _rows(dsn, "session_events")
    outbox_before = _rows(dsn, "broker_outbox")
    results = _recover(dsn, batch_size=batch_size)
    if batch_size == 1:
        results = (*results, *_recover(dsn, batch_size=1))
    assert [(item.accepted_event_id, item.status) for item in results] == [
        (poison.event_id, RecoveryStatus.REQUIRES_RECONCILIATION),
        (healthy.event_id, RecoveryStatus.APPROVED),
    ]
    assert _recover(dsn, batch_size=batch_size) == ()
    pending = next(
        row
        for row in _rows(dsn, "session_command_pending")
        if row["accepted_event_id"] == poison.event_id
    )
    assert pending["status"] == "dead"
    assert pending["recovery_code"] == ("terminal_or_dead" if dead else "invalid_outbox")
    assert _rows(dsn, "session_events") == events_before
    assert all(row in _rows(dsn, "broker_outbox") for row in outbox_before)
    assert not _rows(dsn, "worker_leases")
    assert not _rows(dsn, "command_handoff_receipts")


@pytest.mark.parametrize("field", ["tenant_id", "workspace_id"])
def test_denormalized_scope_mismatch_cannot_quarantine_victim(dsn, field):
    _prepare(dsn)
    _due(dsn)
    from psycopg import sql

    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL("UPDATE session_command_pending SET {}='other'").format(sql.Identifier(field))
        )
        connection.execute("UPDATE broker_outbox SET envelope_json='{}'::jsonb")
    before = _rows(dsn, "session_command_pending")
    assert _recover(dsn) == ()
    assert _rows(dsn, "session_command_pending") == before
    assert not _rows(dsn, "command_recovery_attempts")


def test_database_validation_failure_is_not_swallowed_as_poison(dsn, monkeypatch):
    _prepare(dsn)
    _due(dsn)
    before = _rows(dsn, "session_command_pending")

    def unavailable(*args):
        raise psycopg.OperationalError("synthetic database failure")

    monkeypatch.setattr("agent_storage.postgres.command_wakeup_recovery._validate", unavailable)
    with pytest.raises(psycopg.OperationalError, match="synthetic database failure"):
        _recover(dsn)
    assert _rows(dsn, "session_command_pending") == before
    assert len(_rows(dsn, "broker_outbox")) == 1
    assert not _rows(dsn, "command_recovery_attempts")


def test_new_event_after_approval_prevents_execution_and_rolls_back_new_lease(dsn):
    command = _prepare(dsn)
    _due(dsn)
    _recover(dsn)
    _store(dsn).append(_command(command.session_id, sequence=4, key="new-input"))
    result = _handoff(dsn, command)
    assert result.status is HandoffStatus.REQUIRES_RECONCILIATION and result.lease is None
    assert not _rows(dsn, "worker_leases")


@pytest.mark.parametrize("published", [True, False])
def test_age_budget_and_generation_budget_are_terminal(dsn, published):
    _prepare(dsn)
    _due(dsn)
    with psycopg.connect(dsn) as connection:
        if not published:
            connection.execute("UPDATE broker_outbox SET status='pending', published_at=NULL")
        connection.execute(
            "UPDATE session_command_pending SET created_at = clock_timestamp() "
            "- interval '25 hours'"
        )
    assert _recover(dsn)[0].status is RecoveryStatus.EXHAUSTED
    assert _recover(dsn) == ()


def test_generation_limit_and_causation_chain(dsn):
    _prepare(dsn)
    for generation in range(1, 6):
        _due(dsn)
        assert _recover(dsn)[0].generation == generation
        rows = sorted(_rows(dsn, "broker_outbox"), key=lambda row: row["wake_generation"])
        assert rows[-1]["envelope_json"]["causation_id"] == str(rows[-2]["message_id"])
    _due(dsn)
    assert _recover(dsn)[0].status is RecoveryStatus.EXHAUSTED
    assert len(_rows(dsn, "broker_outbox")) == 6


def test_relay_validates_approved_generation_and_skips_future_due(dsn):
    _prepare(dsn)
    _due(dsn)
    _recover(dsn)
    claims = claim_relay_batch(dsn, deployment_namespace=NAMESPACE, owner="relay")
    assert len(claims) == 1 and claims[0].body == _body(dsn, 1)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE broker_outbox SET status='pending', "
            "available_at=clock_timestamp()+interval '1 hour'"
        )
    assert claim_relay_batch(dsn, deployment_namespace=NAMESPACE, owner="relay") == ()


def test_recovery_scope_does_not_select_other_tenant(dsn):
    _prepare(dsn)
    _due(dsn)
    other = SCOPE.model_copy(update={"tenant_id": "different"})
    assert recover_command_batch(dsn, deployment_namespace=NAMESPACE, scope=other) == ()
    assert not _rows(dsn, "command_recovery_attempts")


def test_generation_without_matching_approval_is_dead_not_published(dsn):
    _prepare(dsn)
    _due(dsn)
    _recover(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_recovery_attempts SET previous_message_id=message_id")
    assert claim_relay_batch(dsn, deployment_namespace=NAMESPACE, owner="relay") == ()
    row = next(row for row in _rows(dsn, "broker_outbox") if row["wake_generation"] == 1)
    assert row["status"] == "dead" and row["last_error_code"] == "invalid_outbox"


def test_recovery_waits_for_refresh_commit_and_does_not_take_over(dsn):
    command = _prepare(dsn)
    _handoff(dsn, command)
    _due(dsn)
    name = f"recovery-refresh-{uuid4()}"
    with ThreadPoolExecutor(max_workers=1) as executor:
        with psycopg.connect(dsn, autocommit=True) as observer:
            with PostgresDatabase(dsn, deployment_namespace=NAMESPACE).connect() as owner:
                # A legitimate heartbeat UPDATE holds its row lock until commit.
                owner.execute(
                    "UPDATE worker_leases SET heartbeat_at=clock_timestamp(), "
                    "expires_at=clock_timestamp()+interval '60 seconds'"
                )
                future = executor.submit(_recover, _worker_dsn(dsn, name))
                _wait_locked(observer, name)
            assert future.result(timeout=5)[0].status is RecoveryStatus.DEFERRED
    assert not _rows(dsn, "command_recovery_attempts")
    assert _rows(dsn, "command_handoff_receipts")[0]["wake_generation"] == 0


def test_post_lock_clock_recovers_when_unchanged_lease_expires_during_wait(dsn):
    command = _prepare(dsn)
    from agent_storage.postgres.command_wakeup_handoff import handoff_command

    original = handoff_command(
        dsn,
        deployment_namespace=NAMESPACE,
        scope=SCOPE,
        accepted_event_id=command.event_id,
        owner_instance_id="old",
        ttl=timedelta(seconds=2),
    )
    _due(dsn)
    name = f"recovery-expiry-{uuid4()}"
    with ThreadPoolExecutor(max_workers=1) as executor:
        with psycopg.connect(dsn, autocommit=True) as observer:
            with psycopg.connect(dsn) as blocker:
                blocker.execute("SELECT * FROM worker_leases FOR UPDATE")
                future = executor.submit(_recover, _worker_dsn(dsn, name))
                _wait_locked(observer, name)
                _wait(observer, "SELECT clock_timestamp() > %s", (original.lease.expires_at,))
            assert future.result(timeout=5)[0].status is RecoveryStatus.APPROVED


@pytest.mark.parametrize("status", ["done", "cancelled", "dead"])
def test_non_pending_never_revives(dsn, status):
    _prepare(dsn)
    _due(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_command_pending SET status=%s", (status,))
    assert _recover(dsn) == ()
    assert len(_rows(dsn, "broker_outbox")) == 1


def test_historical_and_disabled_rollout_do_not_recover(dsn):
    _prepare(dsn, historical=True)
    _due(dsn)
    assert _recover(dsn) == ()
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_command_pending SET origin='live'")
        connection.execute("UPDATE command_wakeup_rollouts SET admission_enabled=false")
    assert _recover(dsn)[0].status is RecoveryStatus.IGNORED
    assert not _rows(dsn, "command_recovery_attempts")


@pytest.mark.parametrize("kind", ["terminal", "missing_floor", "expired_successor"])
def test_ambiguous_or_terminal_attempt_is_not_rebound(dsn, kind):
    command = _prepare(dsn)
    _handoff(dsn, command)
    _expire(dsn, NAMESPACE, command.session_id)
    with psycopg.connect(dsn) as connection:
        if kind == "terminal":
            connection.execute("UPDATE session_projections SET status='cancelled'")
        elif kind == "missing_floor":
            connection.execute("UPDATE command_handoff_receipts SET execution_floor_sequence=NULL")
        else:
            connection.execute("UPDATE worker_leases SET fencing_token=fencing_token+1")
    _due(dsn)
    assert _recover(dsn)[0].status is RecoveryStatus.REQUIRES_RECONCILIATION
    assert not _rows(dsn, "command_recovery_attempts")


@pytest.mark.parametrize("value", [True, False, 0, -1, 101, 1.5])
def test_invalid_batch_rejected_before_connection(value):
    with pytest.raises(ValueError, match="batch size"):
        recover_command_batch(
            "unused", deployment_namespace=NAMESPACE, scope=SCOPE, batch_size=value
        )
