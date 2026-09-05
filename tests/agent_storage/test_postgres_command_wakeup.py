"""Real PostgreSQL atomic admission and canonical wakeup regression."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import PostgresEventStore, PostgresProjectionStore, apply_postgres_migrations
from agent_storage.postgres.client_effects import _append_client_event
from agent_storage.postgres.command_wakeup import CommandAdmissionCapacityError
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from zebra_agent_api.command_submission import submit_session_command

from tests.agent_storage.test_command_wakeup import _binding, _command

NAMESPACE = "command-wakeup-test"


@pytest.fixture(scope="session")
def postgres_dsn():
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn):
    schema = f"command_wakeup_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _seed(dsn, *, tenant="tenant-a", workspace="workspace-a"):
    context = _binding(
        str(uuid4()), tenant=tenant, workspace=workspace
    ).host_capability.host_context
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="command wakeup",
            user_input="synthetic",
            workspace_root="/tmp/no-runtime-used",
            host_context=context,
        )
    )
    PostgresTaskAdmissionTransaction(dsn, deployment_namespace=NAMESPACE).admit(
        TaskAdmissionRequest(
            events=tuple(bootstrap.events),
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            binding=_binding(str(bootstrap.session.session_id), tenant=tenant, workspace=workspace),
        )
    )
    return bootstrap.session


def _enable(dsn):
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """INSERT INTO command_wakeup_rollouts (deployment_namespace, admission_enabled)
               VALUES (%s, TRUE)""",
            (NAMESPACE,),
        )


def _counts(dsn):
    with psycopg.connect(dsn) as connection:
        return tuple(
            connection.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            ).fetchone()[0]
            for table in ("session_command_pending", "broker_outbox")
        )


def _store(dsn):
    return PostgresEventStore(dsn, deployment_namespace=NAMESPACE)


def _accepted(session_id, *, sequence, kind, key):
    command = SessionCommand(
        session_id=session_id,
        kind=kind,
        expected_revision=sequence - 1,
        idempotency_key=key,
    )
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
        idempotency_key=key,
    )


def test_optin_creates_pending_and_envelope_atomically_and_preserves_replay_status(dsn):
    session = _seed(dsn)
    _enable(dsn)
    event = _command(session.session_id)
    assert _store(dsn).append(event) == event
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        pending = connection.execute("SELECT * FROM session_command_pending").fetchone()
        outbox = connection.execute("SELECT * FROM broker_outbox").fetchone()
        assert pending["tenant_id"] == "tenant-a" and pending["workspace_id"] == "workspace-a"
        assert pending["accepted_event_id"] == event.event_id
        assert outbox["envelope_json"]["accepted_event_id"] == str(event.event_id)
        assert outbox["operation_id"] == uuid_from_payload(event)
        connection.execute("UPDATE session_command_pending SET status = 'done'")
        connection.execute("UPDATE broker_outbox SET status = 'published'")
    assert (
        _store(dsn).append(event.model_copy(update={"event_id": uuid4(), "sequence": 99})) == event
    )
    assert _counts(dsn) == (1, 1)
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT status FROM session_command_pending").fetchone() == (
            "done",
        )
        assert connection.execute("SELECT status FROM broker_outbox").fetchone() == ("published",)


def uuid_from_payload(event):
    from uuid import UUID

    return UUID(str(event.payload["command_id"]))


def test_real_api_duplicate_new_random_command_id_returns_canonical(dsn):
    session = _seed(dsn)
    _enable(dsn)
    stores = SimpleNamespace(
        events=_store(dsn), sessions=PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE)
    )
    payload = {"kind": "run", "expected_revision": session.current_sequence}
    first = submit_session_command(
        stores, str(session.session_id), payload, idempotency_key="api-one"
    )
    second = submit_session_command(
        stores, str(session.session_id), payload, idempotency_key="api-one"
    )
    assert first.status_code == 202 and second.status_code == 200
    assert first.body["command_id"] == second.body["command_id"]
    assert _counts(dsn) == (1, 1)


def test_disabled_and_noncommand_leave_no_derived_records(dsn):
    session = _seed(dsn)
    event = _command(session.session_id).model_copy(update={"payload": {"legacy": True}})
    _store(dsn).append(event)
    assert _counts(dsn) == (0, 0)
    _enable(dsn)
    _store(dsn).append(
        event.model_copy(
            update={
                "event_id": uuid4(),
                "sequence": 4,
                "event_type": EventType.SESSION_TITLE_UPDATED,
                "idempotency_key": "title",
                "payload": {"title": "updated"},
            }
        )
    )
    assert _counts(dsn) == (0, 0)


def test_outbox_failure_rolls_back_event_and_pending(dsn):
    session = _seed(dsn)
    _enable(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "ALTER TABLE broker_outbox ADD CONSTRAINT injected_failure CHECK (FALSE)"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        _store(dsn).append(_command(session.session_id))
    assert _counts(dsn) == (0, 0)
    assert _store(dsn).list_for_session(session.session_id)[-1].sequence == session.current_sequence


def test_caller_rollback_removes_all_three_writes(dsn):
    session = _seed(dsn)
    _enable(dsn)
    with pytest.raises(RuntimeError, match="caller rollback"):
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            append_event_in_transaction(connection, NAMESPACE, _command(session.session_id))
            raise RuntimeError("caller rollback")
    assert _counts(dsn) == (0, 0)
    assert _store(dsn).list_for_session(session.session_id)[-1].sequence == session.current_sequence


@pytest.mark.parametrize("damage", ["missing", "tenant", "workspace", "context_digest"])
def test_enabled_missing_or_inconsistent_authority_rolls_back(dsn, damage):
    session = _seed(dsn)
    _enable(dsn)
    with psycopg.connect(dsn) as connection:
        if damage == "missing":
            connection.execute("DELETE FROM task_binding_snapshots")
        elif damage == "tenant":
            connection.execute("UPDATE session_projections SET namespace_id = 'other'")
        elif damage == "workspace":
            connection.execute("DELETE FROM workspace_projections")
        else:
            connection.execute("""UPDATE task_binding_snapshots SET snapshot_json = jsonb_set(
                snapshot_json, '{host_capability,host_context,workspace_ref}', '"tampered"')""")
    with pytest.raises(ValueError, match="command wakeup requires"):
        _store(dsn).append(_command(session.session_id))
    assert _counts(dsn) == (0, 0)
    assert _store(dsn).list_for_session(session.session_id)[-1].sequence == session.current_sequence


def test_concurrent_canonical_append_creates_one_generation(dsn):
    session = _seed(dsn)
    _enable(dsn)
    event = _command(session.session_id)
    barrier = Barrier(2)

    def append(event_id):
        barrier.wait(timeout=5)
        return _store(dsn).append(event.model_copy(update={"event_id": event_id}))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(append, [uuid4(), uuid4()]))
    assert results[0] == results[1]
    assert _counts(dsn) == (1, 1)


def test_derived_records_can_be_rebuilt_without_new_message_identity(dsn):
    session = _seed(dsn)
    _enable(dsn)
    event = _store(dsn).append(_command(session.session_id))
    with psycopg.connect(dsn) as connection:
        original = connection.execute(
            "SELECT message_id, envelope_digest FROM broker_outbox"
        ).fetchone()
        connection.execute("DELETE FROM broker_outbox")
        connection.execute("DELETE FROM session_command_pending")
    _store(dsn).append(event)
    with psycopg.connect(dsn) as connection:
        assert (
            connection.execute("SELECT message_id, envelope_digest FROM broker_outbox").fetchone()
            == original
        )


def test_different_digest_is_rejected_not_overwritten(dsn):
    session = _seed(dsn)
    _enable(dsn)
    event = _store(dsn).append(_command(session.session_id))
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE broker_outbox SET envelope_digest = %s", ("f" * 64,))
    with pytest.raises(ValueError, match="digest conflicts"):
        _store(dsn).append(event)
    assert _counts(dsn) == (1, 1)


def test_client_effect_common_append_projects_epoch_specific_event(dsn):
    session = _seed(dsn)
    _enable(dsn)
    event = _command(session.session_id)
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        _append_client_event(
            connection,
            NAMESPACE,
            session.session_id,
            EventType.SESSION_COMMAND_ACCEPTED,
            EventActor.HARNESS,
            event.payload | {"kind": "resume"},
            idempotency_key="effect:epoch",
        )
    assert _counts(dsn) == (1, 1)
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT envelope_json->>'idempotency_key' FROM broker_outbox"
        ).fetchone() == ("effect:epoch",)


def test_future_producer_timestamp_does_not_delay_outbox(dsn):
    session = _seed(dsn)
    _enable(dsn)
    future = datetime.now(UTC) + timedelta(days=2)
    event = _command(session.session_id).model_copy(update={"created_at": future})
    _store(dsn).append(event)
    with psycopg.connect(dsn) as connection:
        row = connection.execute("""SELECT available_at <= clock_timestamp(),
            created_at <= clock_timestamp(), envelope_json->>'occurred_at' FROM broker_outbox""")
        assert row.fetchone() == (True, True, future.isoformat())


@pytest.mark.parametrize(
    ("limit_column", "second_tenant", "code"),
    [
        ("max_pending_per_scope", "tenant-a", "command_scope_capacity"),
        ("max_unpublished_outbox", "tenant-b", "command_outbox_capacity"),
    ],
)
def test_live_admission_capacity_is_atomic_and_preserves_canonical_stream(
    dsn, limit_column, second_tenant, code
):
    first = _seed(dsn)
    second = _seed(dsn, tenant=second_tenant)
    _enable(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL("UPDATE command_wakeup_rollouts SET {}=1, reserved_control_outbox=0").format(
                sql.Identifier(limit_column)
            )
        )
    _store(dsn).append(_command(first.session_id, key="first"))
    before = _store(dsn).list_for_session(second.session_id)
    with pytest.raises(CommandAdmissionCapacityError, match=f"^{code}$"):
        _store(dsn).append(
            _command(second.session_id, sequence=before[-1].sequence + 1, key="second")
        )
    assert _store(dsn).list_for_session(second.session_id) == before
    assert _counts(dsn) == (1, 1)


def test_concurrent_live_admissions_share_one_scope_slot(dsn):
    sessions = [_seed(dsn), _seed(dsn)]
    _enable(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_wakeup_rollouts SET max_pending_per_scope=1")
    barrier = Barrier(2)

    def admit(index):
        barrier.wait()
        try:
            _store(dsn).append(_command(sessions[index].session_id, key=f"concurrent-{index}"))
            return "accepted"
        except CommandAdmissionCapacityError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(admit, range(2)))
    assert sorted(outcomes) == ["accepted", "command_scope_capacity"]
    assert _counts(dsn) == (1, 1)
    assert (
        sum(
            event.event_type is EventType.SESSION_COMMAND_ACCEPTED
            for session in sessions
            for event in _store(dsn).list_for_session(session.session_id)
        )
        == 1
    )


@pytest.mark.parametrize(
    ("limit_column", "tenant", "status_code", "code"),
    [
        ("max_pending_per_scope", "tenant-a", 429, "command_scope_capacity"),
        ("max_unpublished_outbox", "tenant-b", 503, "command_outbox_capacity"),
    ],
)
def test_api_reports_capacity_without_persisting_rejected_command(
    dsn, limit_column, tenant, status_code, code
):
    first = _seed(dsn)
    rejected = _seed(dsn, tenant=tenant)
    _enable(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL("UPDATE command_wakeup_rollouts SET {}=1, reserved_control_outbox=0").format(
                sql.Identifier(limit_column)
            )
        )
    _store(dsn).append(_command(first.session_id, key="first"))
    before = _store(dsn).list_for_session(rejected.session_id)
    stores = SimpleNamespace(
        events=_store(dsn), sessions=PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE)
    )
    response = submit_session_command(
        stores,
        str(rejected.session_id),
        {"kind": "run", "expected_revision": before[-1].sequence},
        idempotency_key="rejected",
    )
    assert response.status_code == status_code
    assert response.body == {
        "session_id": str(rejected.session_id),
        "status": "capacity_limited",
        "reason": code,
    }
    assert _store(dsn).list_for_session(rejected.session_id) == before
    assert _counts(dsn) == (1, 1)


def test_execution_saturation_preserves_reserved_control_admission(dsn):
    session = _seed(dsn)
    _enable(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """UPDATE command_wakeup_rollouts
               SET max_pending_per_scope=1, max_pending_control_per_scope=1,
                   max_unpublished_outbox=2, reserved_control_outbox=1"""
        )
    _store(dsn).append(
        _accepted(session.session_id, sequence=3, kind=SessionCommandKind.RUN, key="run")
    )
    control = _accepted(
        session.session_id,
        sequence=4,
        kind=SessionCommandKind.CANCEL,
        key="cancel",
    )
    assert _store(dsn).append(control) == control
    assert _counts(dsn) == (2, 2)


def test_idempotent_retry_is_not_rejected_when_outbox_is_at_capacity(dsn):
    session = _seed(dsn)
    _enable(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """UPDATE command_wakeup_rollouts
               SET max_unpublished_outbox=1, reserved_control_outbox=0"""
        )
    event = _command(session.session_id, key="idempotent-at-capacity")
    assert _store(dsn).append(event) == event
    assert _store(dsn).append(event.model_copy(update={"event_id": uuid4()})) == event
    assert _counts(dsn) == (1, 1)
