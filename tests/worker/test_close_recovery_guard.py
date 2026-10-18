"""Shared closure guard and no-model failure classification, with real Recorder writes."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseFence, LeaseLostError, WorkerLease
from agent_core.domain.sessions import SessionStatus
from agent_storage import SessionEventSequenceConflictError
from test_completion_recovery import refresh, seeded
from test_execution_preflight_order import NOW, _recorder, _run_preflight, _seed_pending_close
from zebra_agent_worker import execution_recovery
from zebra_agent_worker.completion_recovery import (
    reconcile_completion,
    recover_committed_completion,
)
from zebra_agent_worker.execution_errors import CompletionRecoveryPending, RetryableWorkerSetupError
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.execution_finalization import reconcile_pending_turn_close
from zebra_agent_worker.execution_preflight import run_with_stale_retry


def newer_event(sid, sequence, kind):
    if kind is EventType.USER_MESSAGE_RECEIVED:
        payload = {"origin": "human", "content": "new", "turn_id": str(uuid4()), "turn_index": 1}
        actor = EventActor.USER
    elif kind is EventType.SESSION_COMMAND_ACCEPTED:
        payload = {
            "command_id": str(uuid4()),
            "session_id": str(sid),
            "kind": "run",
            "expected_revision": sequence - 1,
            "idempotency_key": "new-run",
            "payload": {},
            "fingerprint": "a" * 64,
        }
        actor = EventActor.USER
    else:
        payload, actor = {"attempt_number": 2}, EventActor.HARNESS
    return SessionEvent.create(
        session_id=sid, sequence=sequence, event_type=kind, actor=actor, payload=payload
    )


@pytest.mark.parametrize(
    "kind",
    [
        EventType.USER_MESSAGE_RECEIVED,
        EventType.SESSION_COMMAND_ACCEPTED,
        EventType.HARNESS_ATTEMPT_STARTED,
    ],
)
@pytest.mark.parametrize("entry", ["shared", "old_preflight", "early"])
def test_all_close_callers_refuse_newer_turn_run_or_attempt(tmp_path, kind, entry):
    stores, _, _, sid = _seed_pending_close(tmp_path)
    before = stores.events.list_for_session(sid)
    stores.events.append(newer_event(sid, before[-1].sequence + 1, kind))
    recorder = refresh(stores, sid)
    events = stores.events.list_for_session(sid)
    with pytest.raises(CompletionRecoveryPending):
        if entry == "shared":
            reconcile_pending_turn_close(recorder=recorder, events=events, started_at=NOW)
        elif entry == "early":
            reconcile_completion(recorder, events, NOW)
        else:
            _run_preflight(stores, recorder.session, recorder.workspace, sid, artifact_store=False)
    assert stores.events.list_for_session(sid) == events


@pytest.mark.parametrize("race", ["refresh", "append_cas"])
def test_shared_default_revision_guard_defers_races_without_terminal(tmp_path, race):
    stores, session, workspace, sid = _seed_pending_close(tmp_path)
    recorder = _recorder(stores, session, workspace)
    events = stores.events.list_for_session(sid)
    if race == "refresh":
        stores.events.append(
            newer_event(sid, events[-1].sequence + 1, EventType.USER_MESSAGE_RECEIVED)
        )
    else:
        recorder.append_event = Mock(side_effect=SessionEventSequenceConflictError("lost sequence"))
    with pytest.raises(CompletionRecoveryPending):
        reconcile_pending_turn_close(recorder=recorder, events=events, started_at=NOW)
    assert not any(
        e.event_type is EventType.SESSION_COMPLETED for e in stores.events.list_for_session(sid)
    )


def test_early_answer_cas_loss_does_not_reenter_inputs_or_model(tmp_path):
    recorder, stores, sid, _ = seeded(tmp_path)
    recorder.append_event = Mock(side_effect=SessionEventSequenceConflictError("lost sequence"))
    factory = SimpleNamespace(
        completion_reader=Mock(return_value=stores.events.list_for_session(sid)),
        build=Mock(return_value=recorder),
    )
    service = SimpleNamespace(_projection_recorder_factory=factory, _task_index_store=object())
    claimed = SimpleNamespace(
        recovery=SimpleNamespace(session=recorder.session, workspace=recorder.workspace),
        lease=SimpleNamespace(session_id=sid),
    )
    execute = Mock(
        side_effect=lambda _: recover_committed_completion(service, claimed, Mock(), NOW)
    )
    recover = Mock(side_effect=AssertionError("must not retry execution/model preparation"))
    with pytest.raises(CompletionRecoveryPending):
        run_with_stale_retry(execute, recover=recover, ownership_check=Mock())
    assert execute.call_count == 1
    recover.assert_not_called()
    assert stores.events.list_for_session(sid)[-1].event_type is EventType.ANSWER_COMMITTED


def test_outer_worker_classifies_recovery_pending_without_setup_failure_and_releases_lease(
    monkeypatch,
):
    now = datetime.now(UTC)
    lease = WorkerLease(
        session_id=uuid4(),
        fence=LeaseFence(control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="guard"),
        acquired_at=now,
        heartbeat_at=now,
        expires_at=now + timedelta(seconds=30),
    )
    claimed = SimpleNamespace(
        lease=lease, recovery=SimpleNamespace(session=SimpleNamespace(status=SessionStatus.RUNNING))
    )
    claim_service = SimpleNamespace(heartbeat_lease=Mock(return_value=lease), release_lease=Mock())
    failure = Mock(side_effect=AssertionError("must not write setup failure"))
    monkeypatch.setattr(execution_recovery, "finalize_worker_setup_failure", failure)
    service = SimpleNamespace(
        _claim_service=claim_service,
        _resume_service=SimpleNamespace(
            require_resumable=Mock(return_value=SimpleNamespace(claimed=claimed))
        ),
        _execute_claimed_session_once=Mock(side_effect=CompletionRecoveryPending("defer close")),
    )
    with pytest.raises(CompletionRecoveryPending):
        execution_recovery._execute_with_heartbeat(service, claimed, now, 30)
    assert issubclass(CompletionRecoveryPending, RetryableWorkerSetupError)
    failure.assert_not_called()
    assert service._execute_claimed_session_once.call_count == 1
    claim_service.release_lease.assert_called_once_with(lease)


@pytest.mark.parametrize("control", ["lost_lease", "cancel"])
def test_shared_guard_keeps_fresh_lease_and_cancel_checks(tmp_path, control):
    stores, session, workspace, sid = _seed_pending_close(tmp_path)
    recorder = _recorder(stores, session, workspace)
    events = stores.events.list_for_session(sid)
    if control == "lost_lease":
        recorder._ownership_check = Mock(side_effect=LeaseLostError("lost fence"))
        expected = LeaseLostError
    else:
        stores.events.append(
            SessionEvent.create(
                session_id=sid,
                sequence=events[-1].sequence + 1,
                event_type=EventType.SESSION_CANCELLED,
                actor=EventActor.SYSTEM,
                payload={},
            )
        )
        expected = ExecutionInterrupted
    with pytest.raises(expected):
        reconcile_pending_turn_close(recorder=recorder, events=events, started_at=NOW)
    assert not any(
        e.event_type is EventType.SESSION_COMPLETED for e in stores.events.list_for_session(sid)
    )


def test_same_key_integrity_conflict_is_not_relabelled_as_transient(tmp_path):
    stores, session, workspace, sid = _seed_pending_close(tmp_path)
    recorder = _recorder(stores, session, workspace)
    recorder.append_event = Mock(side_effect=ValueError("idempotency payload conflict"))
    with pytest.raises(ValueError, match="idempotency payload conflict") as error:
        reconcile_pending_turn_close(
            recorder=recorder, events=stores.events.list_for_session(sid), started_at=NOW
        )
    assert not isinstance(error.value, CompletionRecoveryPending)
