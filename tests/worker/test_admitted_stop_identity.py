"""Mandatory real-PG proof for an admitted control fact after execution expiry."""

import pytest
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_storage.postgres.direct_control import PostgresDirectControl
from psycopg import connect

from tests.agent_storage.test_host_management import (
    host_management_dsn as postgres_dsn,  # noqa:F401
)
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn
from tests.worker.test_command_recovery_postgres import (
    test_stop_queued_before_expiry_cancels_after_expiry_without_execution as _expired_stop,
)

dsn = _dsn


def test_admitted_expired_stop_finishes_but_new_expired_host_request_is_denied(
    dsn, tmp_path, monkeypatch
):
    _expired_stop(dsn, tmp_path, monkeypatch)
    with connect(dsn) as db:
        row = db.execute(
            "SELECT snapshot_json FROM task_binding_snapshots WHERE deployment_namespace=%s",
            (NAMESPACE,),
        ).fetchone()
    binding = TaskBindingSnapshot.model_validate(row[0])
    context = binding.host_capability.host_context
    control = PostgresDirectControl(dsn, deployment_namespace=NAMESPACE)
    with pytest.raises(ValueError, match="expired"):
        control.host_scope(binding.task_id, context)
    from datetime import timedelta
    from uuid import UUID, uuid4

    from agent_core.domain.events import EventType

    from tests.agent_storage.test_postgres_command_wakeup import _store

    session_id = UUID(binding.task_id)
    events = _store(dsn).list_for_session(session_id)
    admitted = next(e for e in events if e.event_type is EventType.SESSION_COMMAND_ACCEPTED)
    scope = control.host_scope(session_id, context, admitted_event=admitted)
    forged = admitted.model_copy(update={"created_at": admitted.created_at - timedelta(seconds=1)})
    with pytest.raises(ValueError, match="canonical event"):
        control.host_scope(session_id, context, admitted_event=forged)
    with pytest.raises(ValueError, match="canonical event"):
        control.host_scope(session_id, context, admitted_event=events[0])
    with pytest.raises(ValueError, match="operation conflicts"):
        control.cancel(
            session_id,
            scope=scope,
            host_context=context,
            workspace_ref=context.workspace_ref,
            operation_id=uuid4(),
            admitted_event=admitted,
        )
    assert _store(dsn).list_for_session(session_id) == events


def test_command_differing_from_durable_fingerprint_cannot_cancel(dsn, tmp_path, monkeypatch):
    from zebra_agent_worker.control import SessionControlError

    from tests.agent_storage.test_postgres_command_wakeup import _seed, _store
    from tests.worker.test_command_recovery_postgres import _loop, _stop

    session = _seed(dsn)
    command = _stop(dsn, session)
    before = _store(dsn).list_for_session(session.session_id)
    control = _loop(dsn, tmp_path, monkeypatch)._command_consumer._control_service
    with pytest.raises(SessionControlError, match="differs"):
        control.cancel_command(command.model_copy(update={"idempotency_key": "different-original"}))
    assert _store(dsn).list_for_session(session.session_id) == before
