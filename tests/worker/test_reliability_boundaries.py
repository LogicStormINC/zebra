"""Offline checks at classification, finalization and late-receipt boundaries."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.turns import InteractionMode
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports.execution_inputs import ExecutionInputLimitExceeded
from psycopg import OperationalError
from psycopg.errors import LockNotAvailable
from test_client_effect_resume import NOW, SESSION, _event, _stream
from test_completion_recovery import seeded
from zebra_agent_worker.client_effect_continuation import (
    has_trusted_client_effect_resume,
    restore_client_effect_wait,
)
from zebra_agent_worker.client_effect_resume import recover_client_effect_wakeup
from zebra_agent_worker.completion_recovery import preserve_committed_result
from zebra_agent_worker.continuation_lifecycle import restore_suspended_session_claim
from zebra_agent_worker.execution_completion import finish_execution
from zebra_agent_worker.execution_errors import WorkerExecutionError, exception_attempt_result
from zebra_agent_worker.execution_input_preparation import ExecutionInputEventView


@pytest.mark.parametrize("fault", [LockNotAvailable, OperationalError])
@pytest.mark.parametrize("status", ["complete", "partial", "blocked"])
@pytest.mark.parametrize("mode", [InteractionMode.CONVERSATION, InteractionMode.ONE_SHOT])
def test_storage_fault_after_answer_uses_canonical_completion(tmp_path, status, mode, fault):
    recorder, stores, sid, answer = seeded(tmp_path, status=status, mode=mode.value)
    recorder._events.append(answer)
    prepare = Mock(side_effect=ExecutionInputLimitExceeded("1 MiB"))
    result = finish_execution(
        recorder=recorder,
        attempt_result=exception_attempt_result(fault("offline injection"), {}),
        memory_extraction_service=None,
        memory_promotion_service=None,
        title_service=None,
        event_store=ExecutionInputEventView(
            stores.events,
            prepare,
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
        interaction_mode=mode,
    )
    expected = "awaiting_turn" if mode is InteractionMode.CONVERSATION else "completed"
    assert result.session.status.value == (expected if status == "complete" else "suspended")
    assert result.attempt_result.outcome.value == (
        "completed" if status == "complete" else "suspended"
    )
    prepare.assert_not_called()
    assert stores.events.list_for_session(sid)[answer.sequence] == answer


@pytest.mark.parametrize(
    "reason",
    [
        "execution_authority_unavailable",
        "provider_continuation_uncertain",
        "execution_commit_confirmation_pending",
        "verification_required",
    ],
)
def test_complete_answer_does_not_override_other_suspensions(tmp_path, reason):
    _, _, _, answer = seeded(tmp_path)
    prior = HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.SUSPENDED,
        summary="paused",
        metadata={"stop_reason": reason, "retryable": False},
    )
    assert preserve_committed_result([answer], prior, attempt_number=1) is prior


@pytest.mark.parametrize(
    "boundary,payload",
    [
        (EventType.SESSION_SUSPENDED, {"reason": reason, "metadata": {"retryable": False}})
        for reason in (
            "execution_storage_contention",
            "execution_authority_unavailable",
            "provider_continuation_uncertain",
            "verification_required",
            "user_requested",
        )
    ]
    + [
        (EventType.TURN_COMPLETED, {}),
        (EventType.TURN_FAILED, {}),
        (EventType.TURN_CANCELLED, {}),
        (EventType.USER_MESSAGE_RECEIVED, {}),
        (EventType.APPROVAL_REQUESTED, {}),
        (EventType.CLARIFICATION_REQUESTED, {}),
        *[
            (EventType.SESSION_COMMAND_ACCEPTED, {"kind": kind})
            for kind in ("stop", "cancel", "suspend")
        ],
    ],
)
@pytest.mark.parametrize("receipt_first", [False, True])
def test_late_receipt_cannot_cross_pause_or_turn_boundary(boundary, payload, receipt_first):
    base = _stream()
    # Recovery consumes persisted events; isolate boundary handling from payload schemas.
    marker = base[1].model_copy(update={"event_type": boundary, "payload": payload, "sequence": 2})
    events = (
        base + [marker.model_copy(update={"sequence": 3})]
        if receipt_first else base[:2] + [marker, base[2].model_copy(update={"sequence": 3})]
    )
    assert not has_trusted_client_effect_resume(events)
    recorder = Mock()
    assert not restore_client_effect_wait(recorder, events)
    recorder.append.assert_not_called()
    assert recover_client_effect_wakeup(events) is None
    claim = SimpleNamespace(
        lease=SimpleNamespace(session_id=SESSION),
        recovery=SimpleNamespace(
            session=SimpleNamespace(
                session_id=SESSION, status=SessionStatus.SUSPENDED, current_sequence=3
            )
        ),
    )
    store = Mock()
    store.list_for_session.return_value = events
    with pytest.raises(WorkerExecutionError):
        restore_suspended_session_claim(
            claim,
            cloud_deployment=True,
            control_service=None,
            recovery_service=Mock(),
            started_at=NOW,
            event_store=store,
        )
    store.append.assert_not_called()


def test_valid_receipt_still_recovers_after_own_resume():
    events = _stream()
    assert has_trusted_client_effect_resume(events)
    events.append(
        _event(
            3,
            EventType.SESSION_RESUMED,
            EventActor.HARNESS,
            {"reason": "waiting_client_effect_resolved"},
        )
    )
    assert recover_client_effect_wakeup(events) is not None


@pytest.mark.parametrize("boundary", [EventType.USER_MESSAGE_RECEIVED,
    EventType.HARNESS_ATTEMPT_STARTED, EventType.TURN_COMPLETED, EventType.SESSION_CANCELLED,
    EventType.SESSION_SUSPENDED, EventType.SESSION_WAITING_FOR_CLIENT_EFFECT])
def test_post_answer_storage_fault_preserves_later_control_and_attempt_identity(tmp_path, boundary):
    _, _, _, answer = seeded(tmp_path)
    prior = exception_attempt_result(LockNotAvailable("test"), {})
    assert preserve_committed_result([], prior, attempt_number=1) is prior
    assert preserve_committed_result([answer], prior, attempt_number=2) is prior
    marker = answer.model_copy(update={"sequence": answer.sequence + 1,
        "event_type": boundary, "payload": {}})
    assert preserve_committed_result([answer, marker], prior, attempt_number=1) is prior
