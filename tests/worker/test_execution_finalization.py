from datetime import UTC, datetime

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.sessions import SessionStatus
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.execution_finalization import finalize_execution


class SuspensionRecorder:
    def __init__(self) -> None:
        self.session = type("SessionState", (), {"status": SessionStatus.RUNNING})()
        self.events: tuple[tuple[EventType, EventActor, dict[str, object]], ...] = ()

    def append(
        self,
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, object],
    ) -> None:
        self.events = (*self.events, (event_type, actor, payload))


class InterruptedRecorder(SuspensionRecorder):
    def append(
        self,
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, object],
    ) -> None:
        raise ExecutionInterrupted("durable cancellation won finalization")


def test_budget_exhaustion_is_persisted_as_suspension_not_failure() -> None:
    recorder = SuspensionRecorder()
    result = HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.SUSPENDED,
        summary="explicit tool budget reached",
        metadata={
            "stop_reason": "tool_call_budget_exhausted",
            "tool_call_limit": 2,
        },
    )

    events = finalize_execution(
        recorder=recorder,  # type: ignore[arg-type]
        attempt_result=result,
        memory_extraction_service=None,  # type: ignore[arg-type]
        memory_promotion_service=None,  # type: ignore[arg-type]
        title_service=None,  # type: ignore[arg-type]
        event_store=None,  # type: ignore[arg-type]
        started_at=datetime(2026, 7, 20, tzinfo=UTC),
    )

    assert events[0][0] is EventType.SESSION_SUSPENDED
    assert events[0][2]["reason"] == "tool_call_budget_exhausted"
    assert all(event[0] is not EventType.SESSION_FAILED for event in events)


def test_durable_terminal_state_wins_finalization_race() -> None:
    recorder = InterruptedRecorder()
    result = HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="provider failed after cancellation",
    )

    events = finalize_execution(
        recorder=recorder,  # type: ignore[arg-type]
        attempt_result=result,
        memory_extraction_service=None,  # type: ignore[arg-type]
        memory_promotion_service=None,  # type: ignore[arg-type]
        title_service=None,  # type: ignore[arg-type]
        event_store=None,  # type: ignore[arg-type]
        started_at=datetime(2026, 7, 20, tzinfo=UTC),
    )

    assert events == ()
