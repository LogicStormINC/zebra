"""Real PostgreSQL legacy discovery, cancellation receipt and lease revocation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import psycopg
import pytest
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventType
from agent_storage.postgres.legacy_command_candidates import LegacyCommandCandidates
from zebra_agent_worker.control import SessionControlError
from zebra_agent_worker.loop import build_worker_loop_service

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg
from tests.test_cloud_api_worker_profile_composition import _cloud_settings
from tests.worker.test_command_consumer import _command_event
from tests.worker.test_command_recovery import _settings

dsn = _dsn
postgres_dsn = _pg


def _loop(dsn, tmp_path, monkeypatch):
    monkeypatch.setattr("zebra_agent_worker.loop.SessionExecutionService", lambda **kw: Mock())
    return build_worker_loop_service(
        database_path=tmp_path / "unused",
        settings=_settings(),
        cloud_composition=replace(_cloud_settings(), dsn=dsn, deployment_namespace=NAMESPACE),
    )


def _stop(dsn, session):
    revision = _store(dsn).list_for_session(session.session_id)[-1].sequence
    command = SessionCommand(
        session_id=session.session_id,
        kind=SessionCommandKind.STOP,
        expected_revision=revision,
        idempotency_key=str(session.session_id),
    )
    _store(dsn).append(_command_event(command, revision + 1))
    return command


def test_composed_legacy_stop_has_durable_receipt_and_revokes_lease(dsn, tmp_path, monkeypatch):
    from agent_storage import PostgresLeaseStore, bootstrap_control_plane_epoch

    session = _seed(dsn)
    command = _stop(dsn, session)
    leases = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    leases.acquire(session.session_id, owner_instance_id="old-worker", ttl=timedelta(seconds=30))
    loop = _loop(dsn, tmp_path, monkeypatch)
    consumer = loop._command_consumer
    assert consumer.consume_once(worker_id="w", lease_ttl_seconds=30).status == "executed"
    events = _store(dsn).list_for_session(session.session_id)
    assert events[-1].event_type is EventType.SESSION_CANCELLED
    assert [e.event_type for e in events].count(EventType.TURN_CANCELLED) == 1
    replay = consumer._control_service.cancel_command(command)
    assert replay.event == events[-1]
    assert _store(dsn).list_for_session(session.session_id) == events
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT released_at IS NOT NULL FROM worker_leases WHERE session_id=%s",
            (session.session_id,),
        ).fetchone() == (True,)
        assert connection.execute(
            "SELECT operation_id FROM direct_control_operations",
        ).fetchall() == [(command.command_id,)]
        assert connection.execute("SELECT count(*) FROM command_runtime_cleanup").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM session_command_pending").fetchone() == (0,)
    assert not (tmp_path / "unused").exists()


def test_poison_page_does_not_starve_older_commands_or_drop_intents(dsn, tmp_path, monkeypatch):
    sessions = sorted((_seed(dsn) for _ in range(10)), key=lambda s: s.session_id)
    for session in sessions:
        _stop(dsn, session)
    consumer = _loop(dsn, tmp_path, monkeypatch)._command_consumer
    cancel = consumer._cancel_command

    def fail_first_page(command):
        if command.session_id != sessions[-1].session_id:
            raise SessionControlError("authority temporarily unavailable")
        return cancel(command)

    consumer._cancel_command = fail_first_page
    assert consumer.consume_once(worker_id="w", lease_ttl_seconds=30).status == "skipped"
    assert consumer.consume_once(worker_id="w", lease_ttl_seconds=30).status == "executed"
    remaining = LegacyCommandCandidates(dsn, deployment_namespace=NAMESPACE)(500, None)
    assert [s.session_id for s in remaining] == [s.session_id for s in sessions[:-1]]
    # A new process rediscovers every failed intent, without promoting them to completed.
    restarted = _loop(dsn, tmp_path, monkeypatch)._command_consumer
    assert restarted.consume_once(worker_id="w", lease_ttl_seconds=30).status == "executed"


def test_discovery_is_namespace_scoped_and_bounded(dsn):
    session = _seed(dsn)
    _stop(dsn, session)
    assert LegacyCommandCandidates(dsn, deployment_namespace="other")(8, None) == []
    with pytest.raises(ValueError, match="limit"):
        LegacyCommandCandidates(dsn, deployment_namespace=NAMESPACE)(501, None)


def test_stop_queued_before_expiry_cancels_after_expiry_without_execution(
    dsn, tmp_path, monkeypatch
):
    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
    from agent_core.application.workspace_projection import rebuild_workspace
    from agent_core.domain.task_bindings import host_context_digest
    from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
    from agent_storage.postgres.task_admission import (
        PostgresTaskAdmissionTransaction,
        load_task_binding,
    )

    from tests.agent_storage.test_command_wakeup import _binding

    admitted_at = datetime.now(UTC) - timedelta(minutes=5)
    expires_at = admitted_at + timedelta(minutes=1)
    template = _binding("template")
    context = template.host_capability.host_context.model_copy(update={"expires_at": expires_at})
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="delayed stop",
            user_input="synthetic",
            workspace_root=tmp_path,
            host_context=context,
            created_at=admitted_at,
        )
    )
    session = bootstrap.session
    binding = template.model_copy(
        update={
            "task_id": str(session.session_id),
            "bound_at": admitted_at,
            "host_capability": template.host_capability.model_copy(
                update={
                    "host_context": context,
                    "grant_digest": host_context_digest(context),
                    "grant_expires_at": expires_at,
                    "bound_at": admitted_at,
                }
            ),
        }
    )
    PostgresTaskAdmissionTransaction(dsn, deployment_namespace=NAMESPACE).admit(
        TaskAdmissionRequest(
            events=bootstrap.events,
            session=session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            binding=binding,
        )
    )
    command = SessionCommand(
        session_id=session.session_id,
        kind=SessionCommandKind.STOP,
        expected_revision=session.current_sequence,
        idempotency_key="queued-stop",
    )
    event = _command_event(command, session.current_sequence + 1).model_copy(
        update={"created_at": admitted_at + timedelta(seconds=1)},
    )
    _store(dsn).append(event)
    assert event.created_at < expires_at < datetime.now(UTC)
    consumer = _loop(dsn, tmp_path, monkeypatch)._command_consumer
    assert consumer.consume_once(worker_id="w", lease_ttl_seconds=30).status == "executed"
    consumer._execution_service.execute_session.assert_not_called()
    assert [e.event_type for e in _store(dsn).read_since(session.session_id, event.sequence)] == [
        EventType.TURN_CANCELLED,
        EventType.SESSION_CANCELLED,
    ]
    assert (
        load_task_binding(
            dsn,
            deployment_namespace=NAMESPACE,
            task_id=session.session_id,
        )
        == binding
    )
    consumer._control_service.cancel_command(command)  # Expired replay remains idempotent.


@pytest.mark.parametrize("poison", ["fingerprint", "malformed", "suspend"])
def test_permanent_rejection_survives_restart_and_later_stop(dsn, tmp_path, monkeypatch, poison):
    from agent_storage.postgres.legacy_command_candidates import LEGACY_REJECTION_ACTION

    session = _seed(dsn)
    kind = SessionCommandKind.SUSPEND if poison == "suspend" else SessionCommandKind.RUN
    command = SessionCommand(
        session_id=session.session_id,
        kind=kind,
        expected_revision=session.current_sequence,
        idempotency_key="poison",
    )
    event = _command_event(command, session.current_sequence + 1)
    if poison == "fingerprint":
        event = event.model_copy(update={"payload": {**event.payload, "fingerprint": "0" * 64}})
    elif poison == "malformed":
        event = event.model_copy(update={"payload": {"kind": "run"}})
    _store(dsn).append(event)
    consumer = _loop(dsn, tmp_path, monkeypatch)._command_consumer
    with monkeypatch.context() as guard:
        guard.setattr("zebra_agent_worker.control.build_runtime", Mock(side_effect=AssertionError))
        outcome = consumer.consume_once(worker_id="w", lease_ttl_seconds=30)
    assert outcome.reason == ("unsupported_control" if poison == "suspend" else "invalid_command")
    consumer._execution_service.execute_session.assert_not_called()
    assert _store(dsn).list_for_session(session.session_id)[-1] == event
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT idempotency_key FROM control_plane_idempotency_records WHERE action=%s",
            (LEGACY_REJECTION_ACTION,),
        ).fetchall() == [(str(event.event_id),)]
        assert connection.execute("SELECT count(*) FROM command_control_receipts").fetchone() == (
            0,
        )
    restarted = _loop(dsn, tmp_path, monkeypatch)._command_consumer
    assert restarted.consume_once(worker_id="w", lease_ttl_seconds=30).status == "idle"
    _stop(dsn, session)
    assert restarted.consume_once(worker_id="w", lease_ttl_seconds=30).status == "executed"
    assert (
        _store(dsn).list_for_session(session.session_id)[-1].event_type
        is EventType.SESSION_CANCELLED
    )


def test_stop_overtakes_a_retryable_command_in_same_session(dsn, tmp_path, monkeypatch):
    session = _seed(dsn)
    command = SessionCommand(
        session_id=session.session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=session.current_sequence,
        idempotency_key="blocked-run",
    )
    _store(dsn).append(_command_event(command, session.current_sequence + 1))
    consumer = _loop(dsn, tmp_path, monkeypatch)._command_consumer
    consumer._execution_service.execute_session.side_effect = ValueError("temporary failure")
    assert consumer.consume_once(worker_id="w", lease_ttl_seconds=30).status == "skipped"
    consumer._execution_service.execute_session.reset_mock()
    _stop(dsn, session)
    consumer = _loop(dsn, tmp_path, monkeypatch)._command_consumer
    assert consumer.consume_once(worker_id="w", lease_ttl_seconds=30).status == "executed"
    consumer._execution_service.execute_session.assert_not_called()
