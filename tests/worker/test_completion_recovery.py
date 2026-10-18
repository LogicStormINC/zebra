"""No-model crash-window checks using the real event Recorder and projections."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.turns import InteractionMode
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports.execution_inputs import ExecutionInputLimitExceeded
from test_execution_preflight_order import NOW, _recorder, _seed_pending_close
from zebra_agent_worker.completion_recovery import (
    preserve_committed_result,
    reconcile_completion,
)
from zebra_agent_worker.execution_completion import finish_execution
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.execution_input_preparation import ExecutionInputEventView
from zebra_agent_worker.execution_preflight import StaleExecutionSnapshot

# Reuse the existing disposable-schema native fixture; never touch application data.
from tests.worker.test_bounded_session_recovery import NS, seed
from tests.worker.test_bounded_session_recovery import native as native_fixture
from tests.worker.test_bounded_worker_replay import indexed as indexed_fixture
from tests.worker.test_bounded_worker_replay import replace as replace_native

native = native_fixture
indexed = indexed_fixture


def seeded(tmp_path, *, status="complete", mode="conversation", number=1):
    stores, _, _, sid = _seed_pending_close(tmp_path, with_turn=False, interaction_mode=mode)
    events = stores.events.list_for_session(sid)
    answer = SessionEvent.create(
        session_id=sid,
        sequence=events[-1].sequence + 1,
        event_type=EventType.ANSWER_COMMITTED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": number,
            "assistant_message": "Original answer",
            "delivery_assessment": {
                "status": status,
                "unmet": [] if status == "complete" else ["model_call_budget_exhausted"],
            },
        },
    )
    stores.events.append(answer)
    return refresh(stores, sid), stores, sid, answer


def refresh(stores, sid):
    events = stores.events.list_for_session(sid)
    session, workspace = rebuild_session(events), rebuild_workspace(events)
    stores.sessions.save_session(session)
    stores.workspaces.save_workspace(workspace)
    return _recorder(stores, session, workspace)


@pytest.mark.parametrize(
    "mode,expected", [("conversation", "awaiting_turn"), ("one_shot", "completed")]
)
def test_answer_commit_crash_recovers_without_inputs_or_model(tmp_path, mode, expected):
    recorder, stores, sid, answer = seeded(tmp_path, mode=mode)
    events = stores.events.list_for_session(sid)
    result = reconcile_completion(recorder, events, NOW)
    assert result.session.status.value == expected
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert stores.events.list_for_session(sid)[-1].payload["attempt_number"] == 1
    assert stores.events.list_for_session(sid)[answer.sequence] == answer
    second = reconcile_completion(refresh(stores, sid), stores.events.list_for_session(sid), NOW)
    assert second is None


@pytest.mark.parametrize("status", ["partial", "blocked"])
def test_incomplete_answer_is_suspended_not_success(tmp_path, status):
    recorder, stores, sid, _ = seeded(tmp_path, status=status)
    result = reconcile_completion(recorder, stores.events.list_for_session(sid), NOW)
    assert result.session.status.value == "suspended"
    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.attempt_result.metadata["delivery_assessment"]["status"] == status
    assert not any(
        e.event_type is EventType.TURN_COMPLETED for e in stores.events.list_for_session(sid)
    )


def test_two_phase_close_reuses_existing_reconciliation(tmp_path):
    stores, session, workspace, sid = _seed_pending_close(tmp_path)
    result = reconcile_completion(
        _recorder(stores, session, workspace), stores.events.list_for_session(sid), NOW
    )
    assert result.session.status.value == "completed"
    assert [e.event_type for e in result.events] == [EventType.SESSION_COMPLETED]


def test_fresh_lease_and_cancel_still_win(tmp_path):
    recorder, stores, sid, _ = seeded(tmp_path)
    before = len(stores.events.list_for_session(sid))
    recorder._ownership_check = Mock(side_effect=LeaseLostError("lost fence"))
    with pytest.raises(LeaseLostError):
        reconcile_completion(recorder, stores.events.list_for_session(sid), NOW)
    assert len(stores.events.list_for_session(sid)) == before
    recorder = refresh(stores, sid)
    stores.events.append(
        SessionEvent.create(
            session_id=sid,
            sequence=before,
            event_type=EventType.SESSION_CANCELLED,
            actor=EventActor.USER,
            payload={"reason": "cancel"},
        )
    )
    with pytest.raises(ExecutionInterrupted):
        reconcile_completion(recorder, stores.events.list_for_session(sid)[:-1], NOW)
    assert stores.events.list_for_session(sid)[-1].event_type is EventType.SESSION_CANCELLED


def test_new_message_race_does_not_close_wrong_turn(tmp_path):
    recorder, stores, sid, _ = seeded(tmp_path)
    events = stores.events.list_for_session(sid)
    stores.events.append(
        SessionEvent.create(
            session_id=sid,
            sequence=events[-1].sequence + 1,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={
                "origin": "human",
                "content": "New question",
                "turn_id": str(uuid4()),
                "turn_index": 1,
            },
        )
    )
    with pytest.raises(StaleExecutionSnapshot):
        reconcile_completion(recorder, events, NOW)
    assert (
        reconcile_completion(refresh(stores, sid), stores.events.list_for_session(sid), NOW) is None
    )
    assert stores.events.list_for_session(sid)[-1].event_type is EventType.USER_MESSAGE_RECEIVED


def test_foreign_attempt_and_foreign_session_fail_closed(tmp_path):
    recorder, stores, sid, _ = seeded(tmp_path, number=2)
    events = stores.events.list_for_session(sid)
    with pytest.raises(ValueError, match="Attempt"):
        reconcile_completion(recorder, events, NOW)

    with pytest.raises(ValueError, match="Session"):
        reconcile_completion(recorder, [events[-1].model_copy(update={"session_id": uuid4()})], NOW)


@pytest.mark.parametrize(
    "status,expected", [("complete", "completed"), ("partial", "failed"), ("blocked", "failed")]
)
def test_cleanup_cannot_invert_only_proven_complete_answer(tmp_path, status, expected):
    recorder, _, _, answer = seeded(tmp_path, status=status)
    failure = HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="cleanup failed",
        metadata={"stop_reason": "runtime_cleanup_failed"},
    )
    result = preserve_committed_result([answer], failure, attempt_number=1)
    assert result.outcome.value == expected
    assert preserve_committed_result([answer], failure, attempt_number=2) is failure


def test_finish_execution_uses_committed_answer_for_cleanup_failure(tmp_path):
    recorder, stores, sid, answer = seeded(tmp_path)
    # This recorder represents the active Attempt, whose sink already appended the answer.
    recorder._events.append(answer)
    result = finish_execution(
        recorder=recorder,
        attempt_result=HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.FAILED,
            summary="cleanup failed",
            metadata={"stop_reason": "runtime_cleanup_failed"},
        ),
        memory_extraction_service=None,
        memory_promotion_service=None,
        title_service=None,
        event_store=ExecutionInputEventView(
            stores.events,
            Mock(side_effect=ExecutionInputLimitExceeded("1 MiB")),
            SimpleNamespace(session_id=sid),
            admitted_events=stores.events.list_for_session(sid),
        ),
        cloud_memory_store=object(),
        deployment_namespace="test",
        projection_store=stores.sessions,
        workspace_store=stores.workspaces,
        task_index_store=object(),
        session_id=sid,
        started_at=NOW,
        interaction_mode=InteractionMode.CONVERSATION,
    )
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.session.status.value == "awaiting_turn"


def test_early_recovery_has_no_input_provider_or_tool_setup(tmp_path):
    recorder, stores, sid, _ = seeded(tmp_path)
    factory = SimpleNamespace(
        completion_reader=Mock(return_value=stores.events.list_for_session(sid)),
        build=Mock(return_value=recorder),
    )
    service = SimpleNamespace(_projection_recorder_factory=factory, _task_index_store=object())
    claimed = SimpleNamespace(
        recovery=SimpleNamespace(session=recorder.session, workspace=recorder.workspace),
        lease=SimpleNamespace(session_id=sid),
    )
    from zebra_agent_worker.execution import SessionExecutionService

    result = SessionExecutionService._execute_claimed_session_once(
        service, claimed, ownership_check=Mock(), started_at=NOW
    )
    assert result.session.status.value == "awaiting_turn"
    factory.completion_reader.assert_called_once()


def test_native_completion_reader_skips_large_tools_but_keeps_exact_identity(indexed):
    from agent_core.ports.execution_inputs import ExecutionInputState
    from agent_storage.postgres.worker_replay_reader import PostgresWorkerReplayReader

    state = seed(indexed, 40)
    for sequence in range(10, 26):
        replace_native(
            indexed,
            sequence,
            EventType.TOOL_EXECUTION_COMPLETED,
            {"tool_name": "files.read", "status": "executed", "output": "x" * 100_000},
        )
    replace_native(
        indexed, 38, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}, EventActor.HARNESS
    )
    replace_native(
        indexed,
        39,
        EventType.ANSWER_COMMITTED,
        {
            "attempt_number": 1,
            "assistant_message": "Original",
            "delivery_assessment": {"status": "complete"},
        },
        EventActor.HARNESS,
    )
    full = state.events.list_for_session(state.session_id)
    with pytest.raises(ExecutionInputLimitExceeded, match="1 MiB"):
        ExecutionInputState(events=tuple(full)).encoded()
    authority = state.authority.model_copy(update={"expected_stream_revision": 39})
    reader = PostgresWorkerReplayReader(indexed, deployment_namespace=NS)
    selected = reader.completion_events(authority)
    assert selected[-1] == full[-1]
    assert not any(e.event_type is EventType.TOOL_EXECUTION_COMPLETED for e in selected)
    assert len(selected) < 10
    with pytest.raises(LeaseLostError):
        reader.completion_events(
            authority.model_copy(
                update={
                    "lease_fence": authority.lease_fence.model_copy(update={"fencing_token": 99})
                }
            )
        )


def test_native_completion_reader_still_refuses_oversize_lifecycle_evidence(indexed):
    from agent_storage.postgres.worker_replay_reader import (
        PostgresWorkerReplayReader,
        WorkerReplayLimitExceeded,
    )

    state = seed(indexed, 40)
    for sequence in (38, 39):
        replace_native(
            indexed,
            sequence,
            EventType.USER_MESSAGE_RECEIVED,
            {"content": "x" * 700_000},
            EventActor.USER,
        )
    authority = state.authority.model_copy(update={"expected_stream_revision": 39})
    with pytest.raises(WorkerReplayLimitExceeded):
        PostgresWorkerReplayReader(indexed, deployment_namespace=NS).completion_events(authority)


def test_complete_label_with_unmet_requirements_never_becomes_success(tmp_path):
    recorder, stores, sid, _ = seeded(tmp_path)
    events = stores.events.list_for_session(sid)
    events[-1] = events[-1].model_copy(
        update={
            "payload": {
                **events[-1].payload,
                "delivery_assessment": {"status": "complete", "unmet": ["verification_required"]},
            }
        }
    )
    result = reconcile_completion(recorder, events, NOW)
    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.session.status.value == "suspended"


def test_older_committed_answer_cannot_override_newer_attempt_or_question(tmp_path):
    _, _, sid, answer = seeded(tmp_path)
    failure = HarnessAttemptResult(outcome=HarnessAttemptOutcome.FAILED, summary="failed")
    for kind, payload, actor in [
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}, EventActor.HARNESS),
        (
            EventType.USER_MESSAGE_RECEIVED,
            {"origin": "human", "content": "next", "turn_id": str(uuid4()), "turn_index": 1},
            EventActor.USER,
        ),
    ]:
        later = SessionEvent.create(
            session_id=sid,
            sequence=answer.sequence + 1,
            event_type=kind,
            actor=actor,
            payload=payload,
        )
        assert preserve_committed_result([answer, later], failure, attempt_number=1) is failure


@pytest.mark.parametrize(
    "kind,status,actor",
    [
        (EventType.TURN_FAILED, "failed", EventActor.HARNESS),
        (EventType.TURN_CANCELLED, "cancelled", EventActor.SYSTEM),
    ],
)
def test_two_phase_failure_and_system_cancel_keep_original_outcome(tmp_path, kind, status, actor):
    from agent_core.domain.turns import derive_turn_id

    stores, _, _, sid = _seed_pending_close(tmp_path, with_turn=False)
    events = stores.events.list_for_session(sid)
    payload = {"turn_id": str(derive_turn_id(sid, 0)), "turn_index": 0, "reason": "original"}
    if kind is EventType.TURN_FAILED:
        payload.update(closes_segment=True, attempt_number=1)
    stores.events.append(
        SessionEvent.create(
            session_id=sid,
            sequence=events[-1].sequence + 1,
            event_type=kind,
            actor=actor,
            payload=payload,
        )
    )
    recorder = refresh(stores, sid)
    result = reconcile_completion(recorder, stores.events.list_for_session(sid), NOW)
    assert result.session.status.value == status
    assert not any(e.event_type is EventType.SESSION_COMPLETED for e in result.events)
