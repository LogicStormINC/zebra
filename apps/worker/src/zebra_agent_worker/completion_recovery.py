"""Recover durable delivery boundaries without preparing another model input."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

from agent_core.application import current_turn, interaction_mode_of
from agent_core.contracts.answer_events import AnswerCommittedPayload
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.turns import InteractionMode
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult

from zebra_agent_worker.execution_finalization import (
    ExecutedSession,
    pending_turn_close,
    rebuild_task_index,
    reconcile_pending_turn_close,
)


def preserve_committed_result(
    events: Sequence[SessionEvent],
    prior: HarnessAttemptResult,
    *,
    attempt_number: int,
) -> HarnessAttemptResult:
    """Cleanup/derived failure cannot undo a canonical, complete delivery."""
    answer = next((e for e in reversed(events) if e.event_type is EventType.ANSWER_COMMITTED), None)
    if answer is None or answer.actor is not EventActor.HARNESS:
        return prior
    payload = AnswerCommittedPayload.model_validate(answer.payload)
    if any(
        e.sequence > answer.sequence
        and e.event_type
        in {
            EventType.USER_MESSAGE_RECEIVED,
            EventType.HARNESS_ATTEMPT_STARTED,
            EventType.TURN_COMPLETED,
            EventType.TURN_FAILED,
            EventType.TURN_CANCELLED,
            EventType.SESSION_CANCELLED,
            EventType.SESSION_FAILED,
        }
        for e in events
    ):
        return prior
    if (
        payload.attempt_number != attempt_number
        or payload.delivery_assessment.status != "complete"
        or payload.delivery_assessment.unmet
    ):
        return prior
    # Only failures after this committed answer are normalized; control events
    # still win at the fenced Recorder boundary, never through this result value.
    if prior.outcome not in {HarnessAttemptOutcome.FAILED, HarnessAttemptOutcome.COMPLETED}:
        return prior
    return replace(
        prior,
        outcome=HarnessAttemptOutcome.COMPLETED,
        summary=(
            "Existing committed answer confirmed."
            if prior.outcome is HarnessAttemptOutcome.FAILED
            else prior.summary
        ),
        metadata={
            **prior.metadata,
            **(
                {
                    "post_delivery_failure": prior.metadata.get("stop_reason"),
                    "stop_reason": "committed_answer_confirmed",
                }
                if prior.outcome is HarnessAttemptOutcome.FAILED
                else {}
            ),
            "delivery_assessment": payload.delivery_assessment.model_dump(mode="json"),
            "committed_answer_event_id": str(answer.event_id),
        },
    )


def recover_committed_completion(
    service: Any,
    claimed: Any,
    ownership_check: Callable[[], None],
    started_at: datetime,
) -> ExecutedSession | None:
    """Cloud composition opts in with the existing bounded canonical replay reader."""
    factory = service._projection_recorder_factory
    reader = getattr(factory, "completion_reader", None)
    if reader is None or claimed.recovery.session.status not in {
        SessionStatus.READY,
        SessionStatus.RUNNING,
    }:
        return None
    ownership_check()
    recorder = factory.build(
        session=claimed.recovery.session,
        workspace=claimed.recovery.workspace,
        lease=claimed.lease,
        ownership_check=ownership_check,
    )
    events = reader(recorder.worker_mutation_authority)
    result = reconcile_completion(recorder, events, started_at)
    if result is not None:
        rebuild_task_index(service._task_index_store, claimed.lease.session_id)
    return result


def reconcile_completion(
    recorder: Any,
    events: list[SessionEvent],
    started_at: datetime,
) -> ExecutedSession | None:
    """Use only the last admitted command/Turn/Attempt, never an earlier answer."""
    from zebra_agent_worker.execution_preflight import StaleExecutionSnapshot

    revision = recorder.session.current_sequence
    if any(e.session_id != recorder.session.session_id or e.sequence > revision for e in events):
        raise ValueError("completion evidence crosses Session/revision")
    anchor = max(
        (e.sequence for e in events if e.event_type is EventType.SESSION_COMMAND_ACCEPTED),
        default=-1,
    )
    tail = [e for e in events if e.sequence >= anchor]
    pending = pending_turn_close(tail)
    if pending is not None:
        allowed = (
            {EventActor.HARNESS, EventActor.SYSTEM}
            if pending.event_type is EventType.TURN_CANCELLED
            else {EventActor.HARNESS}
        )
        if pending.actor not in allowed:
            raise ValueError("completion boundary has an invalid actor")
        if any(
            e.event_type is EventType.USER_MESSAGE_RECEIVED and e.sequence > pending.sequence
            for e in tail
        ):
            return None
        return reconcile_pending_turn_close(
            recorder=recorder, events=tail, started_at=started_at, expected_revision=revision
        )
    turn = current_turn(events)
    if turn is None or turn.legacy:
        return None
    answers = [
        e
        for e in tail
        if e.event_type is EventType.ANSWER_COMMITTED and e.sequence > turn.opened_sequence
    ]
    if not answers:
        return None
    if len(answers) != 1 or answers[0].actor is not EventActor.HARNESS:
        raise ValueError("completion requires one canonical Harness answer")
    answer = answers[0]
    payload = AnswerCommittedPayload.model_validate(answer.payload)
    attempts = [e for e in tail if e.event_type is EventType.HARNESS_ATTEMPT_STARTED]
    if (
        not attempts
        or attempts[-1].actor is not EventActor.HARNESS
        or attempts[-1].sequence >= answer.sequence
        or attempts[-1].payload.get("attempt_number") != payload.attempt_number
    ):
        raise ValueError("committed answer disagrees with latest admitted Attempt")
    # A later control/wait boundary is authoritative, not permission to close it.
    if any(
        e.sequence > answer.sequence
        and e.event_type
        in {
            EventType.TURN_COMPLETED,
            EventType.TURN_FAILED,
            EventType.TURN_CANCELLED,
            EventType.SESSION_COMPLETED,
            EventType.SESSION_FAILED,
            EventType.SESSION_CANCELLED,
            EventType.SESSION_SUSPENDED,
            EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
            EventType.APPROVAL_REQUESTED,
            EventType.CLARIFICATION_REQUESTED,
        }
        for e in tail
    ):
        return None
    assessment = payload.delivery_assessment
    complete = assessment.status == "complete" and not assessment.unmet
    metadata = {
        "delivery_assessment": assessment.model_dump(mode="json"),
        "committed_answer_event_id": str(answer.event_id),
        "stop_reason": "committed_answer_recovered"
        if complete
        else "committed_delivery_incomplete",
    }
    result = HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.COMPLETED if complete else HarnessAttemptOutcome.SUSPENDED,
        summary="Recovered existing committed delivery."
        if complete
        else "Existing delivery is incomplete; no automatic model rerun.",
        metadata=metadata,
    )
    closes_segment = interaction_mode_of(events) is not InteractionMode.CONVERSATION
    event = recorder.prepare(
        EventType.TURN_COMPLETED if complete else EventType.SESSION_SUSPENDED,
        EventActor.HARNESS,
        {
            "turn_id": turn.turn_id,
            "turn_index": turn.turn_index,
            "attempt_number": payload.attempt_number,
            "closes_segment": closes_segment,
            "summary": result.summary,
            "metadata": metadata,
        }
        if complete
        else {"reason": "committed_delivery_incomplete", "metadata": metadata},
        created_at=started_at,
    )
    if event.sequence != revision + 1:
        raise StaleExecutionSnapshot("completion recovery lost its canonical revision")
    event = event.model_copy(update={"idempotency_key": f"answer-close:{answer.event_id}"})
    recorder.append_event(event)
    if complete and closes_segment:
        return reconcile_pending_turn_close(
            recorder=recorder,
            events=[event],
            started_at=started_at,
            expected_revision=event.sequence,
        )
    return ExecutedSession(recorder.session, recorder.events, result)
