"""Cloud Handoff checks consume the admitted input view, not canonical history."""

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from zebra_agent_worker.session_handoff import SessionHandoffRecoveryGate, recover_worker_handoff


def _fence():
    return LeaseFence(
        control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="bounded-worker"
    )


def test_supplied_empty_view_never_reads_canonical_history():
    stores = Mock()
    stores.events.list_for_session.side_effect = AssertionError("unbounded history")
    gate = SessionHandoffRecoveryGate("unused", stores=stores)
    assert gate.recover(
        SessionId(uuid4()), fence=_fence(), recovered_at=datetime.now(UTC), events=[]
    ) is None
    stores.events.list_for_session.assert_not_called()


def test_supplied_view_keeps_handoff_envelope_and_started_attempt():
    session_id = SessionId(uuid4())
    handoff_id = str(uuid4())
    events = [
        SessionEvent.create(
            session_id=session_id, sequence=1, event_type=EventType.SESSION_HANDOFF_RECEIVED,
            actor=EventActor.SYSTEM, payload={
                "handoff_id": handoff_id, "parent_session_id": str(uuid4()),
                "root_session_id": str(uuid4()), "stage_index": 1,
                "artifact_id": str(uuid4()), "checksum": "sha256:exact-handoff",
            },
        ),
        SessionEvent.create(
            session_id=session_id, sequence=5, event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS, payload={"attempt_number": 1},
        ),
    ]
    stores = Mock()
    stores.events.list_for_session.side_effect = AssertionError("unbounded history")
    stores.handoffs.get_handoff.return_value.handoff_id = handoff_id
    stores.handoffs.get_envelope.return_value = object()
    gate = SessionHandoffRecoveryGate("unused", stores=stores)
    # Existing envelope interpretation is independent of the input transport.
    from unittest.mock import patch

    with patch(
        "zebra_agent_worker.session_handoff.handoff_runtime_evidence", return_value=object()
    ):
        recovered = recover_worker_handoff(
            gate, session_id, fence=_fence(), recovered_at=datetime.now(UTC),
            release=Mock(), events=events,
        )
    assert recovered.envelope is stores.handoffs.get_envelope.return_value
    stores.events.list_for_session.assert_not_called()
    stores.handoff_dispatch.claim_for_child.assert_not_called()


def test_cross_session_view_is_rejected():
    event = SessionEvent.create(
        session_id=SessionId(uuid4()), sequence=1, event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS, payload={"attempt_number": 1},
    )
    gate = SessionHandoffRecoveryGate("unused", stores=Mock())
    with pytest.raises(ValueError, match="another Session"):
        gate.recover(
            SessionId(uuid4()), fence=_fence(), recovered_at=datetime.now(UTC), events=[event]
        )
