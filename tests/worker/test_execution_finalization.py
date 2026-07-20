from datetime import UTC, datetime

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.sessions import SessionStatus
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
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
        event_store=None,  # type: ignore[arg-type]
        started_at=datetime(2026, 7, 20, tzinfo=UTC),
    )

    assert events[0][0] is EventType.SESSION_SUSPENDED
    assert events[0][2]["reason"] == "tool_call_budget_exhausted"
    assert all(event[0] is not EventType.SESSION_FAILED for event in events)
