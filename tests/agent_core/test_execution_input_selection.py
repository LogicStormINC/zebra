"""Selection contract: execution evidence survives; public presentation does not."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import TaskId, new_event_id, new_session_id
from agent_core.domain.leases import LeaseFence, WorkerLease
from agent_core.ports.agent_tasks import TaskEvent, TaskEventPage
from agent_core.ports.execution_inputs import (
    ExecutionInputHead,
    ExecutionInputState,
    fold_execution_inputs,
)


@pytest.mark.parametrize("kind", list(EventType))
def test_selection_retains_exact_payload_identity_and_source_order(kind):
    session = new_session_id()
    now = datetime.now(UTC)
    lease = WorkerLease(
        session_id=session,
        fence=LeaseFence(control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="test"),
        checkpoint=0,
        acquired_at=now,
        heartbeat_at=now,
        expires_at=now + timedelta(seconds=30),
    )
    event = SessionEvent(
        event_id=new_event_id(),
        session_id=session,
        sequence=0,
        event_type=kind,
        actor=EventActor.HARNESS,
        payload={"exact": "不可丢约束"},
        created_at=now,
        causation_id=new_event_id(),
        correlation_id=uuid4(),
        idempotency_key="binding",
    )
    page = TaskEventPage((TaskEvent(TaskId(session), 0, session, 0, event),), -1, 0, 1024)
    head = fold_execution_inputs(ExecutionInputHead(-1, ExecutionInputState()), page, lease)
    assert head.through_sequence == 0 and head.last_event_id == event.event_id
    assert head.state.session_revision == 0
    presentation = {EventType.MODEL_RESPONSE_DELTA, EventType.PUBLIC_OUTPUT}
    assert head.state.events == (() if kind in presentation else (event,))
