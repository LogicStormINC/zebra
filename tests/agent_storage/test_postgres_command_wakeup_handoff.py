"""Storage-only canonical command handoff; no scheduler or model execution."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage import PostgresLeaseStore, bootstrap_control_plane_epoch
from agent_storage.postgres.command_wakeup import CommandAdmissionCapacityError, _canonical_json
from agent_storage.postgres.command_wakeup_discovery import (
    backfill_command_batch,
    begin_command_backfill,
)
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus, handoff_command
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import acquire_lease_in_transaction, assert_current_lease_fence

from tests.agent_storage.test_command_wakeup import _command
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _enable, _seed, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _postgres_dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup_discovery import SCOPE
from tests.agent_storage.test_postgres_lease_clock import _wait, _wait_locked, _worker_dsn
from tests.agent_storage.test_postgres_leases import _expire

dsn = _dsn_fixture
postgres_dsn = _postgres_dsn_fixture


def _prepare(dsn, *, historical=False, kind="run"):
    session = _seed(dsn)
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    if not historical:
        _enable(dsn)
    command = SessionCommand(
        session_id=session.session_id,
        kind=SessionCommandKind(kind),
        expected_revision=2,
        idempotency_key="handoff",
        payload={"content": "synthetic"} if kind == "message" else {},
    )
    event = SessionEvent.create(
        session_id=session.session_id,
        sequence=3,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
        idempotency_key="handoff",
    )
    _store(dsn).append(event)
    if historical:
        begin_command_backfill(dsn, deployment_namespace=NAMESPACE)
        backfill_command_batch(dsn, deployment_namespace=NAMESPACE)
    return event


def _handoff(dsn, event, **kwargs):
    return handoff_command(
        dsn,
        deployment_namespace=NAMESPACE,
        scope=SCOPE,
        accepted_event_id=event.event_id,
        owner_instance_id="worker",
        ttl=timedelta(seconds=30),
        **kwargs,
    )


def _body(dsn):
    with psycopg.connect(dsn) as connection:
        row = connection.execute("SELECT envelope_json FROM broker_outbox").fetchone()
    return _canonical_json(row[0]).encode()


def _counts(dsn):
    with psycopg.connect(dsn) as connection:
        return tuple(
            connection.execute(
                psycopg.sql.SQL("SELECT count(*) FROM {}").format(psycopg.sql.Identifier(table))
            ).fetchone()[0]
            for table in ("worker_leases", "command_handoff_receipts", "broker_command_inbox")
        )


def test_broker_and_fallback_race_commit_one_lease_receipt_and_inbox(dsn):
    event = _prepare(dsn)
    body = _body(dsn)
    with ThreadPoolExecutor(max_workers=2) as executor:
        broker = executor.submit(_handoff, dsn, event, raw_body=body)
        fallback = executor.submit(_handoff, dsn, event)
        results = [broker.result(timeout=5), fallback.result(timeout=5)]
    assert {result.status for result in results} == {
        HandoffStatus.ACCEPTED,
        HandoffStatus.DUPLICATE,
    }
    assert sum(result.lease is not None for result in results) == 1
    assert _counts(dsn) == (1, 1, 1)
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT fencing_token FROM worker_leases").fetchone() == (1,)
        assert connection.execute("SELECT status FROM session_command_pending").fetchone() == (
            "pending",
        )


def test_handed_off_execution_still_consumes_durable_scope_capacity(dsn):
    event = _prepare(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_wakeup_rollouts SET max_pending_per_scope=1")
    assert _handoff(dsn, event).status is HandoffStatus.ACCEPTED
    second = _seed(dsn)
    with pytest.raises(CommandAdmissionCapacityError, match="command_scope_capacity"):
        _store(dsn).append(_command(second.session_id, key="second"))


def test_failure_after_lease_before_inbox_rolls_back_everything(dsn):
    event = _prepare(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "ALTER TABLE broker_command_inbox ADD CONSTRAINT reject_test CHECK(FALSE)"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        _handoff(dsn, event)
    assert _counts(dsn) == (0, 0, 0)
    with psycopg.connect(dsn) as connection:
        connection.execute("ALTER TABLE broker_command_inbox DROP CONSTRAINT reject_test")
    assert _handoff(dsn, event).status is HandoffStatus.ACCEPTED


def test_historical_backfill_and_duplicate_admission_never_upgrade_origin(dsn):
    event = _prepare(dsn, historical=True)
    _store(dsn).append(event.model_copy(update={"event_id": uuid4(), "sequence": 99}))
    first = _handoff(dsn, event)
    assert first.status is HandoffStatus.REQUIRES_RECONCILIATION and first.lease is None
    assert _handoff(dsn, event).status is HandoffStatus.REQUIRES_RECONCILIATION
    assert _counts(dsn) == (0, 1, 1)
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT origin,status FROM session_command_pending"
        ).fetchone() == ("historical", "pending")


def test_duplicate_of_pre_rollout_event_creates_only_historical_candidate(dsn):
    session = _seed(dsn)
    event = _command(session.session_id)
    _store(dsn).append(event)
    _enable(dsn)
    _store(dsn).append(event)
    assert _handoff(dsn, event).status is HandoffStatus.REQUIRES_RECONCILIATION
    assert _counts(dsn) == (0, 1, 1)


def test_conservative_origin_default_cannot_be_upgraded_by_duplicate(dsn):
    event = _prepare(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_command_pending SET origin = DEFAULT")
    _store(dsn).append(event)
    assert _handoff(dsn, event).status is HandoffStatus.REQUIRES_RECONCILIATION
    assert _counts(dsn) == (0, 1, 1)


def test_first_live_resume_uses_same_canonical_handoff(dsn):
    event = _prepare(dsn, kind="resume")
    result = _handoff(dsn, event, raw_body=_body(dsn))
    assert result.status is HandoffStatus.ACCEPTED
    assert result.lease.session_id == event.session_id
    with psycopg.connect(dsn) as connection:
        receipt = connection.execute(
            "SELECT accepted_event_id, control_plane_epoch, fencing_token, owner_instance_id "
            "FROM command_handoff_receipts"
        ).fetchone()
    assert receipt == (
        event.event_id,
        result.lease.fence.control_plane_epoch,
        result.lease.fence.fencing_token,
        result.lease.fence.owner_instance_id,
    )


def test_busy_keeps_candidate_without_receipt_and_expired_takeover_uses_full_fence(dsn):
    event = _prepare(dsn)
    store = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    old = store.acquire(
        event.session_id, owner_instance_id="other", ttl=timedelta(seconds=30), checkpoint=7
    )
    assert _handoff(dsn, event).status is HandoffStatus.BUSY
    assert _counts(dsn) == (1, 0, 0)
    _expire(dsn, NAMESPACE, event.session_id)
    result = _handoff(dsn, event)
    assert result.status is HandoffStatus.ACCEPTED
    assert result.lease.fence.fencing_token == old.fence.fencing_token + 1
    assert result.lease.checkpoint == 7
    _expire(dsn, NAMESPACE, event.session_id)
    duplicate = _handoff(dsn, event)
    assert duplicate.status is HandoffStatus.DUPLICATE and duplicate.lease is None
    assert store.get(event.session_id) is None


@pytest.mark.parametrize("mismatch", ["tenant", "workspace", "namespace", "body"])
def test_scope_or_body_conflict_does_not_mutate_victim(dsn, mismatch):
    event = _prepare(dsn)
    args = dict(
        deployment_namespace=NAMESPACE,
        scope=SCOPE,
        accepted_event_id=event.event_id,
        owner_instance_id="attacker",
        ttl=timedelta(seconds=30),
    )
    if mismatch == "namespace":
        args["deployment_namespace"] = "foreign"
    elif mismatch == "body":
        args["raw_body"] = _body(dsn) + b" "
    else:
        field = "tenant_id" if mismatch == "tenant" else "workspace_id"
        args["scope"] = SCOPE.model_copy(update={field: "foreign"})
    with pytest.raises(ValueError):
        handoff_command(dsn, **args)
    assert _counts(dsn) == (0, 0, 0)


def test_inbox_digest_conflict_never_reacquires_or_overwrites(dsn):
    event = _prepare(dsn)
    first = _handoff(dsn, event)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE broker_command_inbox SET envelope_digest = 'corrupt'")
    with pytest.raises(ValueError, match="Inbox"):
        _handoff(dsn, event)
    assert _counts(dsn) == (1, 1, 1)
    store = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    assert store.get(event.session_id) == first.lease


@pytest.mark.parametrize("kind", ["stop", "cancel", "suspend"])
def test_other_command_kinds_defer_without_execution_or_inbox(dsn, kind):
    event = _prepare(dsn, kind=kind)
    result = _handoff(dsn, event)
    assert result.status is HandoffStatus.UNSUPPORTED_FOR_EXECUTION_HANDOFF
    assert result.lease is None and _counts(dsn) == (0, 0, 0)


@pytest.mark.parametrize("status", ["cancelled", "completed", "failed"])
def test_terminal_projection_requires_reconciliation_without_lease(dsn, status):
    event = _prepare(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_projections SET status = %s", (status,))
    assert _handoff(dsn, event).status is HandoffStatus.REQUIRES_RECONCILIATION
    assert _counts(dsn) == (0, 1, 1)


@pytest.mark.parametrize("terminal", ["cancelled", "completed", "failed"])
def test_terminal_committed_during_lease_wait_rolls_back_new_acquisition(dsn, terminal):
    event = _prepare(dsn)
    store = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    initial = store.acquire(
        event.session_id, owner_instance_id="old-worker", ttl=timedelta(seconds=2), checkpoint=7
    )
    name = f"handoff-terminal-{uuid4()}"
    with ThreadPoolExecutor(max_workers=1) as executor:
        with psycopg.connect(dsn, autocommit=True) as observer:
            with PostgresDatabase(dsn, deployment_namespace=NAMESPACE).connect() as old_worker:
                assert_current_lease_fence(old_worker, NAMESPACE, event.session_id, initial.fence)
                future = executor.submit(_handoff, _worker_dsn(dsn, name), event)
                _wait_locked(observer, name)
                assert observer.execute(
                    "SELECT clock_timestamp() < %s", (initial.expires_at,)
                ).fetchone()[0]
                old_worker.execute(
                    "UPDATE session_projections SET status = %s "
                    "WHERE deployment_namespace = %s AND session_id = %s",
                    (terminal, NAMESPACE, event.session_id),
                )
                _wait(observer, "SELECT clock_timestamp() > %s", (initial.expires_at,))
            result = future.result(timeout=3)
    assert result.status is HandoffStatus.REQUIRES_RECONCILIATION
    assert result.lease is None and store.get(event.session_id) is None
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT control_plane_epoch, fencing_token, owner_instance_id, checkpoint, "
            "acquired_at, heartbeat_at, expires_at, released_at FROM worker_leases"
        ).fetchone() == (
            initial.fence.control_plane_epoch,
            initial.fence.fencing_token,
            initial.fence.owner_instance_id,
            initial.checkpoint,
            initial.acquired_at,
            initial.heartbeat_at,
            initial.expires_at,
            None,
        )
        assert connection.execute(
            "SELECT status,control_plane_epoch,fencing_token FROM command_handoff_receipts"
        ).fetchone() == ("requires_reconciliation", None, None)
        assert connection.execute("SELECT status FROM broker_command_inbox").fetchone() == (
            "requires_reconciliation",
        )


def test_newer_command_cannot_pass_prior_accepted_command_even_after_lease_expiry(dsn):
    earlier = _prepare(dsn)
    later = _command(earlier.session_id, sequence=4, key="later")
    _store(dsn).append(later)
    assert _handoff(dsn, later).status is HandoffStatus.PRIOR_COMMAND_UNRECONCILED
    assert _handoff(dsn, earlier).status is HandoffStatus.ACCEPTED
    _expire(dsn, NAMESPACE, earlier.session_id)
    assert _handoff(dsn, later).status is HandoffStatus.PRIOR_COMMAND_UNRECONCILED
    assert _counts(dsn) == (1, 1, 1)


@pytest.mark.parametrize(
    "ttl,maximum",
    [
        (timedelta(0), timedelta(seconds=30)),
        (timedelta(seconds=31), timedelta(seconds=30)),
        (timedelta(seconds=1), timedelta(0)),
    ],
)
def test_transaction_lease_helper_validates_ttl_before_any_sql(ttl, maximum):
    with pytest.raises(ValueError, match="ttl"):
        acquire_lease_in_transaction(
            None, "namespace", uuid4(), owner_instance_id="worker", ttl=ttl, maximum_ttl=maximum
        )


def test_transaction_lease_helper_obeys_outer_rollback(dsn):
    event = _prepare(dsn)
    with pytest.raises(RuntimeError, match="rollback"):
        with PostgresDatabase(dsn, deployment_namespace=NAMESPACE).connect() as connection:
            acquire_lease_in_transaction(
                connection,
                NAMESPACE,
                event.session_id,
                owner_instance_id="test",
                ttl=timedelta(seconds=30),
            )
            raise RuntimeError("rollback")
    assert _counts(dsn) == (0, 0, 0)
