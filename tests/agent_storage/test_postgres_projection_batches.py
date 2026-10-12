"""Bounded Worker projections retain canonical content, fence and atomic rollback."""
# ruff: noqa: F401,F811

from datetime import timedelta
from unittest.mock import Mock

import psycopg
import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.leases import LeaseLostError
from agent_storage import PostgresWorkspaceProjectionConflictError
from agent_storage.live_event_store import (
    PostCommitPublishingEventStore,
    with_worker_projection_publisher,
)
from agent_storage.postgres import workspace_projection_batch as batch
from agent_storage.postgres.work_unit import postgres_work_unit

from tests.agent_storage.test_postgres_command_wakeup import (
    NAMESPACE,
    dsn,
    postgres_dsn,
)
from tests.agent_storage.test_postgres_workspaces import (
    _authority,
    _events,
    _events_store,
    _seed_session,
    _sessions,
    _store,
    _workspace_fault,
)


def seed(dsn, count):
    from agent_storage import bootstrap_control_plane_epoch

    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    created, prepared = _events(new_session_id())
    lease = _seed_session(dsn, NAMESPACE, created)
    tail = (
        prepared,
        *(
            SessionEvent.create(
                session_id=created.session_id,
                sequence=i + 2,
                event_type=EventType.RUNTIME_CLEANUP_FAILED,
                actor=EventActor.SYSTEM,
                payload={"target": "runtime", "error_type": "probe", "attempt_number": 1},
            )
            for i in range(count - 1)
        ),
    )
    for event in tail:
        _events_store(dsn, NAMESPACE).append(event)
    history = [created, *tail]
    return lease, tail, rebuild_session(history), rebuild_workspace(history)


@pytest.mark.parametrize("count", [1, 9, 128])
def test_batch_projects_once_and_exact_retry_has_no_writes(dsn, monkeypatch, count):
    lease, tail, session, workspace = seed(dsn, count)
    store = _store(dsn, NAMESPACE)
    authority = _authority(NAMESPACE, lease, expected_revision=0)
    statements = []
    execute = psycopg.Connection.execute

    def counted(connection, query, *args, **kwargs):
        statements.append(str(query))
        return execute(connection, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", counted)
    result = store.project_persisted_worker_events(tail, session, workspace, authority=authority)
    assert result.session == session and result.workspace == workspace
    assert sum("INSERT INTO session_projections" in sql for sql in statements) == 1
    assert sum("INSERT INTO workspace_projections" in sql for sql in statements) == 1
    assert sum("SELECT e.* FROM session_events" in sql for sql in statements) == 1
    statements.clear()
    assert (
        store.project_persisted_worker_events(
            tail,
            session,
            workspace,
            authority=authority,
        )
        == result
    )
    assert not any("INSERT INTO" in sql for sql in statements)


@pytest.mark.parametrize("damage", ["session", "workspace", "event", "gap", "namespace"])
def test_batch_rejects_noncanonical_content_without_projection_writes(dsn, damage):
    lease, tail, session, workspace = seed(dsn, 3)
    authority = _authority(NAMESPACE, lease, expected_revision=0)
    if damage == "session":
        session = session.model_copy(update={"title": "tampered"})
    elif damage == "workspace":
        workspace = workspace.model_copy(update={"workspace_root": "/tmp/other"})
    elif damage == "event":
        tail = (tail[0].model_copy(update={"actor": EventActor.USER}), *tail[1:])
    elif damage == "gap":
        tail = tail[1:]
    else:
        authority = authority.model_copy(update={"deployment_namespace": "foreign"})
    with pytest.raises(PostgresWorkspaceProjectionConflictError):
        _store(dsn, NAMESPACE).project_persisted_worker_events(
            tail,
            session,
            workspace,
            authority=authority,
        )
    assert _sessions(dsn, NAMESPACE).get_session(lease.session_id).current_sequence == 0
    assert _store(dsn, NAMESPACE).get_workspace(lease.session_id) is None


def test_batch_rolls_back_both_projections_and_live_notifications(dsn):
    lease, tail, session, workspace = seed(dsn, 3)
    publisher = Mock()
    store = with_worker_projection_publisher(_store(dsn, NAMESPACE), publisher)
    with _workspace_fault(dsn, NAMESPACE), pytest.raises(psycopg.errors.RaiseException):
        store.project_persisted_worker_events(
            tail,
            session,
            workspace,
            authority=_authority(NAMESPACE, lease, expected_revision=0),
        )
    publisher.publish_committed.assert_not_called()
    assert _sessions(dsn, NAMESPACE).get_session(lease.session_id).current_sequence == 0
    assert _store(dsn, NAMESPACE).get_workspace(lease.session_id) is None
    store.project_persisted_worker_events(
        tail,
        session,
        workspace,
        authority=_authority(NAMESPACE, lease, expected_revision=0),
    )
    assert [call.args[0] for call in publisher.publish_committed.call_args_list] == list(tail)


def test_batch_rechecks_lease_after_projection_writes_and_rolls_back(dsn, monkeypatch):
    lease, tail, session, workspace = seed(dsn, 3)
    save = batch.save_session_in_transaction

    def expire(connection, deployment, value):
        result = save(connection, deployment, value)
        connection.execute(
            "UPDATE worker_leases SET acquired_at=clock_timestamp()-interval '2 seconds', "
            "heartbeat_at=clock_timestamp()-interval '2 seconds', expires_at=clock_timestamp()-%s "
            "WHERE deployment_namespace=%s AND session_id=%s",
            (timedelta(seconds=1), deployment, lease.session_id),
        )
        return result

    monkeypatch.setattr(batch, "save_session_in_transaction", expire)
    with pytest.raises(LeaseLostError):
        _store(dsn, NAMESPACE).project_persisted_worker_events(
            tail,
            session,
            workspace,
            authority=_authority(NAMESPACE, lease, expected_revision=0),
        )
    assert _sessions(dsn, NAMESPACE).get_session(lease.session_id).current_sequence == 0
    assert _store(dsn, NAMESPACE).get_workspace(lease.session_id) is None


@pytest.mark.parametrize("operation", ["batch", "project", "commit"])
@pytest.mark.parametrize("rollback", [False, True])
def test_borrowed_projection_never_publishes_before_outer_commit(dsn, operation, rollback):
    lease, tail, session, workspace = seed(dsn, 1)
    native = _store(dsn, NAMESPACE)
    publisher = Mock()
    store = with_worker_projection_publisher(native, publisher)
    authority = _authority(NAMESPACE, lease, expected_revision=0)

    def project():
        with postgres_work_unit(native._database):
            if operation == "batch":
                result = store.project_persisted_worker_events(
                    tail,
                    session,
                    workspace,
                    authority=authority,
                )
            else:
                method = (
                    store.project_persisted_worker_event
                    if operation == "project"
                    else store.commit_worker_event
                )
                result = method(tail[0], session, workspace, authority=authority)
            assert result.session == session and result.workspace == workspace
            publisher.publish_committed.assert_not_called()
            if rollback:
                raise ValueError("outer owner rolled back")

    if rollback:
        with pytest.raises(ValueError, match="outer owner rolled back"):
            project()
    else:
        project()
    publisher.publish_committed.assert_not_called()
    # Durable replay/primary state, not the skipped live hint, owns visibility.
    assert _events_store(dsn, NAMESPACE).list_for_session(lease.session_id)[-1] == tail[0]
    assert _sessions(dsn, NAMESPACE).get_session(lease.session_id).current_sequence == (
        0 if rollback else 1
    )
    assert _store(dsn, NAMESPACE).get_workspace(lease.session_id) == (
        None if rollback else workspace
    )


@pytest.mark.parametrize("rollback", [False, True])
def test_borrowed_event_append_suppresses_hint_and_preserves_durable_owner(dsn, rollback):
    created, _ = _events(new_session_id())
    native = _events_store(dsn, NAMESPACE)
    publisher = Mock()
    store = PostCommitPublishingEventStore(native, publisher)

    def append():
        with postgres_work_unit(native._database):
            assert store.append(created) == created
            publisher.publish_committed.assert_not_called()
            if rollback:
                raise ValueError("outer owner rolled back")

    if rollback:
        with pytest.raises(ValueError, match="outer owner rolled back"):
            append()
    else:
        append()
    publisher.publish_committed.assert_not_called()
    assert native.list_for_session(created.session_id) == ([] if rollback else [created])
