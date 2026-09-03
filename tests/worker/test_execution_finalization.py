from datetime import UTC, datetime
from uuid import UUID

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.sessions import SessionStatus
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.execution_finalization import finalize_execution


class SuspensionRecorder:
    def __init__(self) -> None:
        self.session = type(
            "SessionState",
            (),
            {"status": SessionStatus.RUNNING, "session_id": UUID(int=0)},
        )()
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


class EmptyEventStore:
    def list_for_session(self, _session_id: object) -> list[object]:
        return []


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


def test_cloud_side_effects_can_leave_the_durable_reply_path() -> None:
    recorder = SuspensionRecorder()

    events = finalize_execution(
        recorder=recorder,  # type: ignore[arg-type]
        attempt_result=HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.COMPLETED,
            summary="reply complete",
        ),
        memory_extraction_service=None,
        memory_promotion_service=None,
        title_service=None,  # type: ignore[arg-type]
        event_store=EmptyEventStore(),  # type: ignore[arg-type]
        cloud_memory_store=object(),  # type: ignore[arg-type]
        started_at=datetime(2026, 8, 29, tzinfo=UTC),
        defer_cloud_side_effects=True,
    )

    assert [event[0] for event in events] == [
        EventType.TURN_COMPLETED,
        EventType.SESSION_COMPLETED,
    ]
