"""Real isolated PostgreSQL: lost ACK recovery never replays an atomic write."""

from contextlib import contextmanager
from time import monotonic
from unittest.mock import Mock

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.leases import LeaseLostError
from agent_core.ports.workspace_projection_store import WorkerCommitConfirmationPending
from agent_storage import PostgresLeaseStore
from agent_storage.postgres.task_io import task_io_deadline

from tests.agent_storage.test_postgres_command_wakeup_receipts import dsn
from tests.agent_storage.test_postgres_workspaces import (
    _authority,
    _events,
    _events_store,
    _seed_session,
    _store,
    postgres_dsn,
    workspace_namespace,
)

__all__ = ["postgres_dsn", "workspace_namespace", "dsn"]


@pytest.mark.parametrize("project_only", [False, True])
@pytest.mark.parametrize(
    "outcome", ["committed", "rolled_back", "newer_event", "lease_lost", "read_timeout"]
)
def test_lost_ack_confirms_exact_commit_or_stays_uncertain(
    postgres_dsn,
    workspace_namespace,
    monkeypatch,
    project_only,
    outcome,
):
    created, event = _events(new_session_id())
    lease = _seed_session(postgres_dsn, workspace_namespace, created)
    session, workspace = rebuild_session([created, event]), rebuild_workspace([created, event])
    authority = _authority(workspace_namespace, lease, expected_revision=0)
    store = _store(postgres_dsn, workspace_namespace)
    events = _events_store(postgres_dsn, workspace_namespace)
    if project_only:
        events.append(event)
    connect = store._database.connect
    writes = []

    @contextmanager
    def lost_ack():
        writes.append(1)
        with connect() as connection:
            yield connection
            if outcome == "rolled_back":
                raise TimeoutError("rollback before COMMIT")
        if outcome == "newer_event":
            events.append(
                SessionEvent.create(
                    session_id=event.session_id,
                    sequence=2,
                    event_type=EventType.USER_MESSAGE_RECEIVED,
                    actor=EventActor.USER,
                    payload={"content": "a new Turn must not be closed"},
                )
            )
        if outcome == "lease_lost":
            PostgresLeaseStore(postgres_dsn, deployment_namespace=workspace_namespace).release(
                event.session_id,
                fence=lease.fence,
            )
        raise TimeoutError("COMMIT acknowledgement lost")

    monkeypatch.setattr(store._database, "connect", lost_ack)
    if outcome == "read_timeout":
        monkeypatch.setattr(
            store._database, "connect_task_io", Mock(side_effect=TimeoutError("DB down"))
        )
    method = store.project_persisted_worker_event if project_only else store.commit_worker_event
    if outcome == "committed":
        result = method(event, session, workspace, authority=authority)
        assert result.event == event and result.session == session and result.workspace == workspace
    else:
        with pytest.raises(
            LeaseLostError if outcome == "lease_lost" else WorkerCommitConfirmationPending
        ):
            method(event, session, workspace, authority=authority)
    assert len(writes) == 1
    stored = events.list_for_session(event.session_id)
    assert sum(x.event_id == event.event_id for x in stored) == (
        0 if outcome == "rolled_back" and not project_only else 1
    )


@pytest.mark.parametrize("mismatch", ["event", "projection", "oversize", "parent_deadline"])
def test_confirmation_cannot_accept_wrong_payload_projection_or_exceed_budget(
    postgres_dsn,
    workspace_namespace,
    monkeypatch,
    mismatch,
):
    created, canonical = _events(new_session_id())
    lease = _seed_session(postgres_dsn, workspace_namespace, created)
    if mismatch == "oversize":
        canonical = canonical.model_copy(
            update={"payload": {**canonical.payload, "note": "x" * 1_048_577}}
        )
    session, workspace = (
        rebuild_session([created, canonical]),
        rebuild_workspace([created, canonical]),
    )
    store = _store(postgres_dsn, workspace_namespace)
    authority = _authority(workspace_namespace, lease, expected_revision=0)
    store.commit_worker_event(canonical, session, workspace, authority=authority)
    attempted = canonical
    if mismatch == "event":
        attempted = canonical.model_copy(
            update={"payload": {**canonical.payload, "title": "different"}}
        )
    if mismatch == "projection":
        session = session.model_copy(update={"title": "not persisted"})

    # Raise from the real operation's transaction boundary without rewriting anything.
    @contextmanager
    def timeout():
        raise TimeoutError("unknown response")
        yield  # pragma: no cover

    monkeypatch.setattr(store._database, "connect", timeout)
    if mismatch == "parent_deadline":
        now = monotonic()
        with pytest.raises(WorkerCommitConfirmationPending), task_io_deadline(now + 1):
            monkeypatch.setattr("agent_storage.postgres.task_io.monotonic", lambda: now + 2)
            store.commit_worker_event(attempted, session, workspace, authority=authority)
    else:
        with pytest.raises(WorkerCommitConfirmationPending):
            store.commit_worker_event(attempted, session, workspace, authority=authority)
    assert _events_store(postgres_dsn, workspace_namespace).list_for_session(
        canonical.session_id
    ) == [created, canonical]


def test_normal_commit_never_runs_confirmation(postgres_dsn, workspace_namespace, monkeypatch):
    created, event = _events(new_session_id())
    lease = _seed_session(postgres_dsn, workspace_namespace, created)
    store = _store(postgres_dsn, workspace_namespace)
    monkeypatch.setattr(
        store._database,
        "connect_task_io",
        Mock(side_effect=AssertionError("unexpected confirmation")),
    )
    result = store.commit_worker_event(
        event,
        rebuild_session([created, event]),
        rebuild_workspace([created, event]),
        authority=_authority(workspace_namespace, lease, expected_revision=0),
    )
    assert result.event == event


@pytest.mark.parametrize("boundary", ["started", "handled"])
@pytest.mark.parametrize("receipt_intact", [True, False])
def test_confirmation_requires_matching_command_receipt(dsn, monkeypatch, boundary, receipt_intact):
    import psycopg
    from agent_storage.postgres.worker_commit_confirmation import _confirm

    from tests.agent_storage import test_postgres_command_wakeup_receipts as receipts

    command, lease = receipts._setup(dsn)
    event = receipts._start(dsn, command, lease)
    if boundary == "handled":
        event = receipts._event(dsn, command.session_id, EventType.SESSION_SUSPENDED)
        receipts._commit(dsn, event, lease)
    sessions, store = receipts._projections(dsn)
    session = sessions.get_session(event.session_id)
    workspace = store.get_workspace(event.session_id)
    authority = _authority(receipts.NAMESPACE, lease, expected_revision=event.sequence - 1)
    if not receipt_intact:
        with psycopg.connect(dsn) as connection:
            column = "started_event_id" if boundary == "started" else "handled_event_id"
            connection.execute(f"UPDATE command_handoff_receipts SET {column}=NULL")
    result = _confirm(store, event, session, workspace, authority)
    assert (result is not None) is receipt_intact
