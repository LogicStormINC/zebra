from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.leases import LeaseFence, LeaseLostError, WorkerLease
from agent_core.domain.turns import InteractionMode, derive_turn_id
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports.execution_inputs import (
    MAX_INPUT_BYTES,
    ExecutionInputLimitExceeded,
    ExecutionInputState,
)
from zebra_agent_worker.execution_input_preparation import ExecutionInputEventView
from zebra_agent_worker.execution_preparation import execution_event_view
from zebra_agent_worker.execution_turn_close import append_turn_close

NOW = datetime(2026, 10, 18, tzinfo=UTC)


def admitted():
    sid = new_session_id()
    lease = WorkerLease(session_id=sid, fence=LeaseFence(control_plane_epoch=uuid4(),
                fencing_token=1, owner_instance_id='test'), acquired_at=NOW,
                heartbeat_at=NOW, expires_at=NOW + timedelta(seconds=60))
    def event(sequence, kind, actor, payload):
        return SessionEvent.create(session_id=sid, sequence=sequence, event_type=kind,
                    actor=actor, payload=payload, created_at=NOW)
    first = str(derive_turn_id(sid, 0))
    second = str(derive_turn_id(sid, 1))
    events = [event(0, EventType.USER_MESSAGE_RECEIVED, EventActor.USER,
                   {'content': 'first', 'origin': 'human', 'turn_id': first, 'turn_index': 0}),
              event(1, EventType.TURN_COMPLETED, EventActor.HARNESS,
                   {'turn_id': first, 'turn_index': 0, 'closes_segment': False}),
              event(2, EventType.USER_MESSAGE_RECEIVED, EventActor.USER,
                   {'content': 'second', 'origin': 'human', 'turn_id': second, 'turn_index': 1})]
    return lease, events


class Recorder:
    def __init__(self, sid):
        self.session = SimpleNamespace(session_id=sid)
        self.calls = []
        self.owner = Mock()

    def append(self, kind, actor, payload):
        self.owner()  # production Recorder still owns fresh control and fencing checks.
        self.calls.append((kind, actor, payload))


@pytest.mark.parametrize('mode,outcome,expected', [
    (InteractionMode.CONVERSATION, HarnessAttemptOutcome.COMPLETED, [EventType.TURN_COMPLETED]),
    (InteractionMode.ONE_SHOT, HarnessAttemptOutcome.COMPLETED,
     [EventType.TURN_COMPLETED, EventType.SESSION_COMPLETED]),
    (InteractionMode.CONVERSATION, HarnessAttemptOutcome.FAILED,
     [EventType.TURN_FAILED, EventType.SESSION_FAILED]),
])
def test_close_uses_admitted_second_turn_without_repreparing_large_inputs(mode, outcome, expected):
    lease, events = admitted()
    reader = Mock(side_effect=ExecutionInputLimitExceeded('over limit'))
    view = execution_event_view(Mock(), reader, lease, Mock(), admitted_events=events)
    # A newer input must not change which Turn this execution is entitled to close.
    events.append(SessionEvent.create(session_id=lease.session_id, sequence=3,
        event_type=EventType.USER_MESSAGE_RECEIVED, actor=EventActor.USER, created_at=NOW,
        payload={'content': 'third', 'origin': 'human', 'turn_index': 2,
                 'turn_id': str(derive_turn_id(lease.session_id, 2))}))
    recorder = Recorder(lease.session_id)
    append_turn_close(recorder=recorder, attempt_result=HarnessAttemptResult(
        outcome=outcome, summary='existing result'), event_store=view,
        interaction_mode=mode, attempt_number=3)
    assert [x[0] for x in recorder.calls] == expected
    assert recorder.calls[0][2]['turn_id'] == str(derive_turn_id(lease.session_id, 1))
    assert recorder.calls[0][2]['turn_index'] == 1
    assert all(x[2]['attempt_number'] == 3 for x in recorder.calls)
    assert recorder.owner.call_count == len(expected)
    reader.assert_not_called()
    # Preparation still fails closed at the original cap; closing does not raise that cap.
    oversized = events[0].model_copy(update={'payload': {'content': 'x' * MAX_INPUT_BYTES}})
    with pytest.raises(ExecutionInputLimitExceeded, match='1 MiB'):
        ExecutionInputState(events=(oversized,)).encoded()


def test_admitted_identity_does_not_bypass_lease_loss_or_invent_unbound_turn():
    lease, events = admitted()
    reader = Mock(side_effect=ExecutionInputLimitExceeded('over limit'))
    view = ExecutionInputEventView(Mock(), reader, lease, admitted_events=events)
    recorder = Recorder(lease.session_id)
    recorder.owner.side_effect = LeaseLostError('lost fence')
    result = HarnessAttemptResult(outcome=HarnessAttemptOutcome.COMPLETED, summary='done')
    with pytest.raises(LeaseLostError):
        append_turn_close(recorder=recorder, attempt_result=result, event_store=view,
                          interaction_mode=InteractionMode.CONVERSATION, attempt_number=1)
    assert not recorder.calls
    unbound = ExecutionInputEventView(Mock(), reader, lease)
    with pytest.raises(ValueError, match='not admitted'):
        append_turn_close(recorder=recorder, attempt_result=result, event_store=unbound,
                          interaction_mode=InteractionMode.CONVERSATION, attempt_number=1)
    reader.assert_not_called()
    with pytest.raises(ValueError, match='cross Session'):
        ExecutionInputEventView(Mock(), reader, lease, admitted_events=[events[0].model_copy(
            update={'session_id': new_session_id()})])
