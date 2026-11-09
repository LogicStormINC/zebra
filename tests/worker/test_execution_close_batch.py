"""Close-burst batching regressions (CA-HA-03 D3).

append_turn_close must stay observably equivalent for duck-typed recorders
(no batch method) and route contiguous close bursts through the recorder's
native batch when present.
"""

from uuid import UUID

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.turns import InteractionMode
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from zebra_agent_worker.execution_turn_close import append_turn_close


def _attempt(completed: bool) -> HarnessAttemptResult:
    return HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.COMPLETED if completed else HarnessAttemptOutcome.FAILED,
        summary="done" if completed else "budget",
        metadata={"stop_reason": "natural"},
    )


class LegacyRecorder:
    """Duck-typed recorder without any batch surface."""

    def __init__(self) -> None:
        self.appends: list[tuple[EventType, EventActor, dict]] = []
        self.session = type(
            "SessionState",
            (),
            {"status": SessionStatus.RUNNING, "session_id": UUID(int=0)},
        )()

    def append(self, event_type, actor, payload):
        self.appends.append((event_type, actor, payload))


class BatchRecorder(LegacyRecorder):
    """Recorder advertising the native close batch."""

    def __init__(self) -> None:
        super().__init__()
        self.batches: list[list[tuple]] = []

    def append_close_batch(self, drafts):
        self.batches.append(list(drafts))
        self.appends.extend(drafts)


class _View:
    admitted_turn = None

    def list_for_session(self, _session_id):
        return []


def test_legacy_recorder_keeps_exact_per_event_appends():
    recorder = LegacyRecorder()
    append_turn_close(
        recorder=recorder,
        attempt_result=_attempt(True),
        event_store=_View(),
        interaction_mode=InteractionMode.CONVERSATION,
        attempt_number=1,
    )
    assert [a[0] for a in recorder.appends] == [EventType.TURN_COMPLETED]
    append_turn_close(
        recorder=recorder,
        attempt_result=_attempt(False),
        event_store=_View(),
        interaction_mode=InteractionMode.ONE_SHOT,
        attempt_number=2,
    )
    assert [a[0] for a in recorder.appends[1:]] == [EventType.TURN_FAILED, EventType.SESSION_FAILED]


def test_batch_recorder_receives_one_close_burst():
    recorder = BatchRecorder()
    append_turn_close(
        recorder=recorder,
        attempt_result=_attempt(False),
        event_store=_View(),
        interaction_mode=InteractionMode.ONE_SHOT,
        attempt_number=1,
    )
    assert len(recorder.batches) == 1
    kinds = [draft[0] for draft in recorder.batches[0]]
    assert kinds == [EventType.TURN_FAILED, EventType.SESSION_FAILED]
    assert all(draft[1] is EventActor.HARNESS for draft in recorder.batches[0])
    # The single-event conversation path never batches.
    append_turn_close(
        recorder=recorder,
        attempt_result=_attempt(True),
        event_store=_View(),
        interaction_mode=InteractionMode.CONVERSATION,
        attempt_number=2,
    )
    assert len(recorder.batches) == 1
    assert recorder.appends[-1][0] is EventType.TURN_COMPLETED
