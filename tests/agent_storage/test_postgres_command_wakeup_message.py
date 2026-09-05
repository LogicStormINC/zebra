"""MESSAGE input, existing lease and receipt atomicity, with real worker multi-turn execution."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from agent_core.application import current_turn, project_turns
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.turns import InteractionMode
from agent_storage.postgres.command_wakeup import _canonical_json
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus, handoff_command
from agent_storage.postgres.command_wakeup_recovery import RecoveryStatus
from psycopg import sql

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_discovery import SCOPE
from tests.agent_storage.test_postgres_command_wakeup_execution import _setup
from tests.agent_storage.test_postgres_command_wakeup_handoff import _handoff, _prepare
from tests.agent_storage.test_postgres_command_wakeup_receipts import (
    _commit,
    _event,
    _refresh,
    _start,
)
from tests.agent_storage.test_postgres_command_wakeup_recovery import _due, _recover, _rows
from tests.agent_storage.test_postgres_leases import _expire

dsn = _dsn_fixture
postgres_dsn = _pg_fixture


def _message(dsn, session_id, *, content="Follow-up input", clarification_id=None):
    previous = _store(dsn).list_for_session(session_id)[-1]
    payload = {"content": content}
    if clarification_id is not None:
        payload["clarification_id"] = clarification_id
    command = SessionCommand(
        session_id=session_id,
        kind=SessionCommandKind.MESSAGE,
        expected_revision=previous.sequence,
        idempotency_key=str(uuid4()),
        payload=payload,
    )
    event = SessionEvent.create(
        session_id=session_id,
        sequence=previous.sequence + 1,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
        idempotency_key=command.idempotency_key,
    )
    return _store(dsn).append(event)


def _awaiting(dsn, tmp_path, monkeypatch):
    service, stores, lease = _setup(
        dsn,
        tmp_path,
        monkeypatch,
        interaction_mode=InteractionMode.CONVERSATION,
    )
    result = service.execute_claimed_session(lease)
    assert result.session.status is SessionStatus.AWAITING_TURN
    return service, stores, lease.session_id


def _receipt(dsn, command):
    return next(
        row
        for row in _rows(dsn, "command_handoff_receipts")
        if row["accepted_event_id"] == command.event_id
    )


def _body(dsn, command, generation=0):
    row = next(
        row
        for row in _rows(dsn, "broker_outbox")
        if str(row["operation_id"]) == command.payload["command_id"]
        and row["wake_generation"] == generation
    )
    return _canonical_json(row["envelope_json"]).encode()


def test_message_handoff_executes_second_turn_with_one_input(dsn, tmp_path, monkeypatch):
    service, stores, session_id = _awaiting(dsn, tmp_path, monkeypatch)
    command = _message(dsn, session_id)
    accepted = _handoff(dsn, command)
    assert accepted.status is HandoffStatus.ACCEPTED
    receipt = _receipt(dsn, command)
    events = stores.events.list_for_session(session_id)
    message = next(event for event in events if event.event_id == receipt["input_event_id"])
    assert message.event_type is EventType.USER_MESSAGE_RECEIVED
    assert message.payload["content"] == "Follow-up input" and message.payload["turn_index"] == 1
    assert message.causation_id == command.event_id
    assert receipt["execution_floor_sequence"] == message.sequence
    assert stores.sessions.get_session(session_id).status is SessionStatus.READY
    assert (
        service.execute_claimed_session(accepted.lease).session.status
        is SessionStatus.AWAITING_TURN
    )
    assert _receipt(dsn, command)["handled_event_id"] is not None
    events = stores.events.list_for_session(session_id)
    assert len(project_turns(events)) == 2 and current_turn(events) is None
    assert sum(event.causation_id == command.event_id for event in events) == 1


def test_duplicate_broker_and_fallback_append_once(dsn, tmp_path, monkeypatch):
    _, stores, session_id = _awaiting(dsn, tmp_path, monkeypatch)
    command = _message(dsn, session_id)
    body = _body(dsn, command)
    barrier = Barrier(2)

    def invoke(raw):
        barrier.wait(timeout=3)
        return _handoff(dsn, command, raw_body=raw)

    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = executor.submit(invoke, None), executor.submit(invoke, body)
        results = a.result(timeout=8), b.result(timeout=8)
    assert {result.status for result in results} == {
        HandoffStatus.ACCEPTED,
        HandoffStatus.DUPLICATE,
    }
    assert sum(result.lease is not None for result in results) == 1
    assert (
        sum(
            event.causation_id == command.event_id
            for event in stores.events.list_for_session(session_id)
        )
        == 1
    )


def test_unstarted_message_recovery_reuses_input_and_new_fence(dsn, tmp_path, monkeypatch):
    _, stores, session_id = _awaiting(dsn, tmp_path, monkeypatch)
    command = _message(dsn, session_id)
    first = _handoff(dsn, command)
    input_id = _receipt(dsn, command)["input_event_id"]
    _expire(dsn, NAMESPACE, session_id)
    _due(dsn)
    recovery = _recover(dsn)
    assert any(
        item.accepted_event_id == command.event_id and item.status is RecoveryStatus.APPROVED
        for item in recovery
    )
    second = _handoff(dsn, command, raw_body=_body(dsn, command, 1))
    assert second.status is HandoffStatus.ACCEPTED
    assert second.lease.fence.fencing_token > first.lease.fence.fencing_token
    assert _receipt(dsn, command)["input_event_id"] == input_id
    assert (
        sum(
            event.causation_id == command.event_id
            for event in stores.events.list_for_session(session_id)
        )
        == 1
    )
    assert _handoff(dsn, command, raw_body=_body(dsn, command, 0)).lease is None


@pytest.mark.parametrize("boundary", ["receipt", "inbox"])
def test_message_failure_rolls_back_input_projections_and_lease(
    dsn, tmp_path, monkeypatch, boundary
):
    _, stores, session_id = _awaiting(dsn, tmp_path, monkeypatch)
    command = _message(dsn, session_id)
    before = (
        stores.events.list_for_session(session_id),
        stores.sessions.get_session(session_id),
        stores.workspaces.get_workspace(session_id),
        _rows(dsn, "worker_leases"),
    )
    with psycopg.connect(dsn) as connection:
        if boundary == "receipt":
            connection.execute(
                "ALTER TABLE command_handoff_receipts ADD CONSTRAINT reject_input "
                "CHECK(input_event_id IS NULL)"
            )
        else:
            connection.execute(
                sql.SQL(
                    "ALTER TABLE broker_command_inbox ADD CONSTRAINT reject_message "
                    "CHECK(accepted_event_id <> {})"
                ).format(sql.Literal(command.event_id))
            )
    with pytest.raises(psycopg.errors.CheckViolation):
        _handoff(dsn, command)
    assert before == (
        stores.events.list_for_session(session_id),
        stores.sessions.get_session(session_id),
        stores.workspaces.get_workspace(session_id),
        _rows(dsn, "worker_leases"),
    )
    assert all(
        row["accepted_event_id"] != command.event_id
        for row in _rows(dsn, "command_handoff_receipts")
    )


def test_bootstrap_open_turn_message_is_reconciled_without_input_or_lease(dsn):
    command = _prepare(dsn, kind="message")
    before = _store(dsn).list_for_session(command.session_id)
    result = _handoff(dsn, command)
    assert result.status is HandoffStatus.REQUIRES_RECONCILIATION and result.lease is None
    assert _store(dsn).list_for_session(command.session_id) == before
    assert not _rows(dsn, "worker_leases")
    assert _handoff(dsn, command).status is HandoffStatus.REQUIRES_RECONCILIATION


def test_later_message_cannot_overtake_unhandled_predecessor(dsn, tmp_path, monkeypatch):
    service, stores, session_id = _awaiting(dsn, tmp_path, monkeypatch)
    first = _message(dsn, session_id, content="first")
    later = _message(dsn, session_id, content="later")
    before = stores.events.list_for_session(session_id)
    assert _handoff(dsn, later).status is HandoffStatus.PRIOR_COMMAND_UNRECONCILED
    assert stores.events.list_for_session(session_id) == before
    first_handoff = _handoff(dsn, first)
    assert first_handoff.status is HandoffStatus.ACCEPTED
    service.execute_claimed_session(first_handoff.lease)
    later_handoff = _handoff(dsn, later)
    assert later_handoff.status is HandoffStatus.ACCEPTED
    input_id = _receipt(dsn, later)["input_event_id"]
    event = next(
        event for event in stores.events.list_for_session(session_id) if event.event_id == input_id
    )
    assert event.payload["content"] == "later" and event.payload["turn_index"] == 2


def test_busy_message_does_not_append_input_or_replace_lease(dsn, tmp_path, monkeypatch):
    _, stores, session_id = _awaiting(dsn, tmp_path, monkeypatch)
    busy = stores.leases.acquire(session_id, owner_instance_id="busy", ttl=timedelta(seconds=30))
    command = _message(dsn, session_id)
    before = stores.events.list_for_session(session_id)
    assert _handoff(dsn, command).status is HandoffStatus.BUSY
    assert stores.events.list_for_session(session_id) == before
    assert stores.leases.get(session_id).fence == busy.fence


def test_message_scope_rejection_does_not_mutate_input(dsn, tmp_path, monkeypatch):
    _, stores, session_id = _awaiting(dsn, tmp_path, monkeypatch)
    command = _message(dsn, session_id)
    before = stores.events.list_for_session(session_id)
    with pytest.raises(ValueError, match="scope"):
        handoff_command(
            dsn,
            deployment_namespace=NAMESPACE,
            scope=SCOPE.model_copy(update={"tenant_id": "victim"}),
            accepted_event_id=command.event_id,
            owner_instance_id="worker",
            ttl=timedelta(seconds=30),
        )
    assert stores.events.list_for_session(session_id) == before


@pytest.mark.parametrize("matching", [True, False, None])
def test_clarification_message_uses_core_matching_validation(dsn, matching):
    original = _prepare(dsn)
    lease = _handoff(dsn, original).lease
    _refresh(dsn, original.session_id)
    _start(dsn, original, lease)
    clarification_id = str(uuid4())
    requested = _event(
        dsn,
        original.session_id,
        EventType.CLARIFICATION_REQUESTED,
        {"clarification_id": clarification_id},
    )
    _commit(dsn, requested, lease)
    _expire(dsn, NAMESPACE, original.session_id)
    command = _message(
        dsn,
        original.session_id,
        clarification_id=(clarification_id if matching else None if matching is None else "wrong"),
    )
    before = _store(dsn).list_for_session(original.session_id)
    result = _handoff(dsn, command)
    if matching:
        assert result.status is HandoffStatus.ACCEPTED
        event = _store(dsn).list_for_session(original.session_id)[-1]
        assert event.event_type is EventType.CLARIFICATION_RESPONDED
        assert event.payload["clarification_id"] == clarification_id
        assert _receipt(dsn, command)["input_event_id"] == event.event_id
    else:
        assert result.status is HandoffStatus.REQUIRES_RECONCILIATION and result.lease is None
        assert _store(dsn).list_for_session(original.session_id) == before
