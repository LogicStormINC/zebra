"""Explicit audited retirement and real Task message -> RUN after historical cutover."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService, current_turn
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import TaskId
from agent_core.domain.turns import InteractionMode
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import (
    PostgresLeaseStore,
    PostgresProjectionStore,
    PostgresWorkspaceProjectionStore,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
from agent_storage.postgres.command_wakeup_cutover import (
    preview_command_retirement,
    retire_historical_commands,
)
from agent_storage.postgres.command_wakeup_discovery import (
    backfill_command_batch,
    begin_command_backfill,
)
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from agent_storage.postgres.task_index_transactions import _lock_task
from psycopg import sql
from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.command_submission import submit_session_command
from zebra_agent_api.task_api import append_task_message

from tests.agent_storage.test_command_wakeup import _binding
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_control import _body, _intent
from tests.agent_storage.test_postgres_command_wakeup_discovery import SCOPE
from tests.agent_storage.test_postgres_command_wakeup_handoff import HandoffStatus, _handoff
from tests.agent_storage.test_postgres_command_wakeup_recovery import _due, _recover, _rows
from tests.agent_storage.test_postgres_lease_clock import _wait_locked, _worker_dsn
from tests.agent_storage.test_postgres_leases import _expire

dsn = _dsn_fixture
postgres_dsn = _pg_fixture


def _append(dsn, session_id, event_type, payload):
    events = _store(dsn).list_for_session(session_id)
    return _store(dsn).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=events[-1].sequence + 1,
            event_type=event_type,
            actor=EventActor.HARNESS,
            payload=payload,
        )
    )


def _history(dsn):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="historical conversation",
            user_input="First input",
            workspace_root="/tmp/unused",
            interaction_mode=InteractionMode.CONVERSATION,
            host_context=_binding("fixture").host_capability.host_context,
        )
    )
    session_id = bootstrap.session.session_id
    PostgresTaskAdmissionTransaction(dsn, deployment_namespace=NAMESPACE).admit(
        TaskAdmissionRequest(
            events=tuple(bootstrap.events),
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            binding=_binding(str(session_id)),
        )
    )
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    commands = (_intent(dsn, session_id, "run"), _intent(dsn, session_id, "resume"))
    _append(dsn, session_id, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    turn = current_turn(_store(dsn).list_for_session(session_id))
    assert turn is not None
    _append(
        dsn,
        session_id,
        EventType.TURN_COMPLETED,
        {
            "turn_id": turn.turn_id,
            "turn_index": turn.turn_index,
            "closes_segment": False,
        },
    )
    events = _store(dsn).list_for_session(session_id)
    PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE).save_session(
        rebuild_session(events)
    )
    PostgresWorkspaceProjectionStore(dsn, deployment_namespace=NAMESPACE).save_workspace(
        rebuild_workspace(events)
    )
    begin_command_backfill(dsn, deployment_namespace=NAMESPACE)
    backfill_command_batch(dsn, deployment_namespace=NAMESPACE)
    return commands


def _preview(dsn, session_id, **kwargs):
    return preview_command_retirement(
        dsn,
        deployment_namespace=NAMESPACE,
        scope=SCOPE,
        task_id=session_id,
        session_id=session_id,
        **kwargs,
    )


def _apply(dsn, preview, **overrides):
    values = asdict(preview)
    values.pop("high_session_id")
    values.pop("high_sequence")
    values.update(
        operator_id="test-operator",
        reason="verified quiescent migration boundary",
        operation_key="retirement-test",
    )
    values.update(overrides)
    scope = values.pop("scope", SCOPE)
    return retire_historical_commands(dsn, deployment_namespace=NAMESPACE, scope=scope, **values)


def test_retirement_allows_real_task_message_then_run_and_old_delivery_never_executes(dsn):
    commands = _history(dsn)
    session_id = commands[0].session_id
    events = _store(dsn).list_for_session(session_id)
    preview = _preview(dsn, session_id)
    assert preview.accepted_event_ids == tuple(command.event_id for command in commands)
    assert not _rows(dsn, "command_retirement_operations")  # preview is read-only
    assert _apply(dsn, preview) == preview
    assert _store(dsn).list_for_session(session_id) == events
    assert not _rows(dsn, "command_handoff_receipts")
    assert _apply(dsn, preview) == preview
    assert len(_rows(dsn, "command_retirement_operations")) == 1
    for command in commands:
        for body in (None, _body(dsn, command)):
            outcome = _handoff(dsn, command, raw_body=body)
            assert outcome.status is HandoffStatus.RETIRED_NOOP and outcome.lease is None
    _due(dsn)
    assert not _recover(dsn)
    stores = SimpleNamespace(
        events=_store(dsn),
        sessions=PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE),
        workspaces=PostgresWorkspaceProjectionStore(dsn, deployment_namespace=NAMESPACE),
        tasks=PostgresAgentTaskStore(dsn, deployment_namespace=NAMESPACE),
        artifact_payloads=None,
    )
    app = ZebraAgentApi(database_path=Path("/not-used"), settings=SimpleNamespace(), _stores=stores)
    response = append_task_message(
        app, str(session_id), {"content": "Second input"}, idempotency_key=None
    )
    assert response.status_code == 201
    assert (
        stores.events.list_for_session(session_id)[-1].event_type is EventType.USER_MESSAGE_RECEIVED
    )
    response = submit_session_command(
        stores,
        str(session_id),
        {
            "kind": "run",
            "expected_revision": stores.events.list_for_session(session_id)[-1].sequence,
        },
        idempotency_key="following-run",
    )
    assert response.status_code == 202
    command = stores.events.list_for_session(session_id)[-1]
    assert command.event_type is EventType.SESSION_COMMAND_ACCEPTED
    assert _handoff(dsn, command).status is HandoffStatus.ACCEPTED
    # Audit replay remains read-only even after the Session advances.
    assert _apply(dsn, preview) == preview


@pytest.mark.parametrize(
    "guard",
    [
        "live",
        "lease",
        "expired_lease",
        "revision",
        "partial",
        "scope",
        "tail",
        "boundary",
        "receipt",
        "task",
    ],
)
def test_retirement_guards_do_not_mutate_history_or_execution(dsn, guard):
    commands = _history(dsn)
    session_id = commands[0].session_id
    preview = _preview(dsn, session_id)
    overrides = {}
    if guard in {"lease", "expired_lease"}:
        PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).acquire(
            session_id, owner_instance_id="old-worker", ttl=timedelta(seconds=30)
        )
        if guard == "expired_lease":
            _expire(dsn, NAMESPACE, session_id)
    elif guard == "revision":
        overrides["expected_revision"] = preview.expected_revision - 1
    elif guard == "partial":
        overrides["accepted_event_ids"] = preview.accepted_event_ids[:1]
    elif guard == "scope":
        overrides["scope"] = SCOPE.model_copy(update={"workspace_id": "foreign"})
    elif guard == "task":
        overrides["task_id"] = uuid4()
    elif guard == "tail":
        _append(dsn, session_id, EventType.MODEL_RESPONSE_RECEIVED, {})
    elif guard == "receipt":
        assert _handoff(dsn, commands[0]).status is HandoffStatus.REQUIRES_RECONCILIATION
    else:
        with psycopg.connect(dsn) as connection:
            if guard == "live":
                connection.execute("UPDATE session_command_pending SET origin='live'")
            elif guard == "boundary":
                connection.execute("UPDATE command_wakeup_rollouts SET high_sequence=1")
    names = (
        "session_events",
        "worker_leases",
        "session_command_pending",
        "command_handoff_receipts",
        "session_projections",
        "workspace_projections",
    )
    before = {name: _rows(dsn, name) for name in names}
    with pytest.raises(ValueError):
        _apply(dsn, preview, **overrides)
    assert before == {name: _rows(dsn, name) for name in names}
    assert not _rows(dsn, "command_retirement_operations")


@pytest.mark.parametrize("table", ["command_retirements", "session_command_pending"])
def test_retirement_write_failure_rolls_back_audit_and_all_pending(dsn, table):
    commands = _history(dsn)
    preview = _preview(dsn, commands[0].session_id)
    before = _rows(dsn, "session_command_pending")
    with psycopg.connect(dsn) as connection:
        check = "status != 'cancelled'" if table == "session_command_pending" else "false"
        connection.execute(
            sql.SQL("ALTER TABLE {} ADD CONSTRAINT fail_retirement CHECK ({})").format(
                sql.Identifier(table), sql.SQL(check)
            )
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        _apply(dsn, preview)
    assert not _rows(dsn, "command_retirement_operations")
    assert not _rows(dsn, "command_retirements")
    assert _rows(dsn, "session_command_pending") == before


def test_retirement_operation_key_cannot_change_audit_identity(dsn):
    command = _history(dsn)[0]
    preview = _preview(dsn, command.session_id)
    _apply(dsn, preview)
    with pytest.raises(ValueError, match="identity conflict"):
        _apply(dsn, preview, reason="different reason")
    assert len(_rows(dsn, "command_retirement_operations")) == 1


def test_title_only_tail_requires_matching_projection_and_fresh_revision(dsn):
    command = _history(dsn)[0]
    old = _preview(dsn, command.session_id)
    _append(dsn, command.session_id, EventType.SESSION_TITLE_UPDATED, {"title": "New title"})
    with pytest.raises(ValueError, match="matching canonical"):
        _preview(dsn, command.session_id)
    events = _store(dsn).list_for_session(command.session_id)
    PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE).save_session(
        rebuild_session(events)
    )
    fresh = _preview(dsn, command.session_id)
    assert fresh.closure_event_id == old.closure_event_id
    with pytest.raises(ValueError, match="stale"):
        _apply(dsn, old)
    assert _apply(dsn, fresh) == fresh


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_revision": True},
        {"accepted_event_ids": ()},
        {"operator_id": ""},
        {"reason": "unsafe\nmetadata"},
        {"operation_key": "x" * 129},
    ],
)
def test_operator_metadata_is_validated_before_connecting(overrides):
    args = dict(
        scope=SCOPE,
        task_id=uuid4(),
        session_id=uuid4(),
        expected_revision=7,
        closure_event_id=uuid4(),
        accepted_event_ids=(uuid4(),),
        operator_id="operator",
        reason="audited migration",
        operation_key="operation",
    )
    args.update(overrides)
    with pytest.raises(ValueError):
        retire_historical_commands("not-a-dsn", deployment_namespace=NAMESPACE, **args)


@pytest.mark.parametrize("head", ["drift", "missing"])
def test_preview_and_apply_reject_invalid_stream_head_without_retiring(dsn, monkeypatch, head):
    import agent_storage.postgres.command_wakeup_cutover as cutover

    command = _history(dsn)[0]
    preview = _preview(dsn, command.session_id)
    if head == "drift":
        with psycopg.connect(dsn) as connection:
            connection.execute(
                "UPDATE session_streams SET current_version=current_version+1 WHERE session_id=%s",
                (command.session_id,),
            )
    else:
        # The FK protects a real missing stream; inject only this read's result,
        # while all other queries, locks and transaction rollback use actual PG.
        eligible = cutover._eligible

        class MissingHead:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, query, parameters):
                if " ".join(query.split()).startswith(
                    "SELECT current_version FROM session_streams"
                ):
                    return SimpleNamespace(fetchone=lambda: None)
                return self.connection.execute(query, parameters)

        def missing(connection, *args):
            return eligible(MissingHead(connection), *args)

        monkeypatch.setattr(cutover, "_eligible", missing)
    names = ("session_events", "session_streams", "session_command_pending", "worker_leases")
    before = {name: _rows(dsn, name) for name in names}
    with pytest.raises(ValueError, match="canonical stream head"):
        _preview(dsn, command.session_id)
    with pytest.raises(ValueError, match="canonical stream head"):
        _apply(dsn, preview)
    assert before == {name: _rows(dsn, name) for name in names}
    assert not _rows(dsn, "command_retirement_operations")
    assert not _rows(dsn, "command_retirements")


def test_retirement_never_waits_on_worker_lease_while_holding_root_task_advisory(dsn):
    command = _history(dsn)[0]
    preview = _preview(dsn, command.session_id)
    PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).acquire(
        command.session_id, owner_instance_id="old-worker", ttl=timedelta(seconds=30)
    )
    before = _rows(dsn, "worker_leases")
    with ThreadPoolExecutor(max_workers=1) as executor:
        with psycopg.connect(dsn) as worker:
            worker.execute("SELECT 1 FROM worker_leases FOR SHARE")
            future = executor.submit(_apply, dsn, preview)
            with pytest.raises(ValueError, match="lease is busy"):
                future.result(timeout=3)
            # A fenced rollover's next Task lock must remain obtainable: no cycle.
            worker.execute("SET LOCAL lock_timeout='1s'")
            _lock_task(worker, NAMESPACE, TaskId(command.session_id))
    assert _rows(dsn, "worker_leases") == before
    assert not _rows(dsn, "command_retirement_operations")


@pytest.mark.parametrize("winner", ["handoff", "retirement"])
def test_retirement_and_old_delivery_serialize_in_both_orders(dsn, monkeypatch, winner):
    import agent_storage.postgres.command_wakeup_cutover as cutover
    import agent_storage.postgres.command_wakeup_handoff as handoff

    command = _history(dsn)[0]
    preview = _preview(dsn, command.session_id)
    entered, release = Event(), Event()
    module, function = (
        (cutover, "_eligible") if winner == "retirement" else (handoff, "_check_inbox")
    )
    original = getattr(module, function)

    def hold(*args, **kwargs):
        entered.set()
        assert release.wait(4)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, function, hold)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = (
            executor.submit(_apply, dsn, preview)
            if winner == "retirement"
            else executor.submit(_handoff, dsn, command)
        )
        try:
            assert entered.wait(3)
            if winner == "handoff":
                with pytest.raises(ValueError, match="boundary is busy"):
                    _apply(dsn, preview)
                second = None
            else:
                name = f"retirement-race-{uuid4()}"
                second = executor.submit(_handoff, _worker_dsn(dsn, name), command)
                with psycopg.connect(dsn, autocommit=True) as observer:
                    _wait_locked(observer, name)
        finally:
            release.set()
        result = first.result(timeout=5)
        if winner == "handoff":
            assert result.status is HandoffStatus.REQUIRES_RECONCILIATION
            with pytest.raises(ValueError, match="existing command receipt"):
                _apply(dsn, preview)
            assert not _rows(dsn, "command_retirement_operations")
        else:
            assert result == preview
            assert second.result(timeout=5).status is HandoffStatus.RETIRED_NOOP
    assert not _rows(dsn, "worker_leases")
