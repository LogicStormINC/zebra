"""Recorder append guards: prevalidation and canonical-sequence handling."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.turns import derive_turn_id
from agent_storage import sqlite_control_plane_stores
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.tool_run_index import ToolRunIndexer

NOW = datetime(2026, 8, 24, 17, 0, tzinfo=UTC)


def _recorder(tmp_path: Path):
    stores = sqlite_control_plane_stores(tmp_path / "recorder.sqlite")
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Recorder guards",
            user_input="Do the work.",
            workspace_root=tmp_path,
        )
    )
    for event in bootstrap.events:
        stores.events.append(event)
    events = stores.events.list_for_session(bootstrap.session.session_id)
    session = rebuild_session(events)
    workspace = rebuild_workspace(events)
    stores.sessions.save_session(session)
    stores.workspaces.save_workspace(workspace)
    recorder = DurableHarnessEventRecorder(
        session=session,
        workspace=workspace,
        event_store=stores.events,
        projection_store=stores.sessions,
        workspace_store=stores.workspaces,
        model_call_indexer=ModelCallIndexer(stores.model_calls),
        tool_run_indexer=ToolRunIndexer(stores.tool_runs),
    )
    return stores, recorder, bootstrap.session.session_id


def test_illegal_transition_never_pollutes_the_event_store(tmp_path: Path) -> None:
    stores, recorder, session_id = _recorder(tmp_path)
    # The bootstrap session is READY; READY -> COMPLETED is illegal.
    illegal = SessionEvent.create(
        session_id=session_id,
        sequence=recorder.next_sequence,
        event_type=EventType.SESSION_COMPLETED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1, "summary": "illegal"},
    )

    with pytest.raises(ValueError, match="invalid session transition"):
        recorder.append_event(illegal)

    events = stores.events.list_for_session(session_id)
    assert all(event.event_type is not EventType.SESSION_COMPLETED for event in events)
    assert rebuild_session(events).status.value == "ready"


def test_stale_idempotent_canonical_does_not_rollback_projection(tmp_path: Path) -> None:
    stores, recorder, session_id = _recorder(tmp_path)
    turn_id = str(derive_turn_id(session_id, 0))

    def marker(sequence: int, key: str) -> SessionEvent:
        return SessionEvent.create(
            session_id=session_id,
            sequence=sequence,
            event_type=EventType.TURN_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"turn_id": turn_id, "turn_index": 0, "closes_segment": False},
            idempotency_key=key,
        )

    # Commit one event normally (sequence 3).
    recorder.append_event(marker(3, "stale-canonical"))
    assert recorder.session.current_sequence == 3

    # Append unrelated progress so the projection advances past it.
    recorder.append_event(
        SessionEvent.create(
            session_id=session_id,
            sequence=4,
            event_type=EventType.SESSION_TITLE_UPDATED,
            actor=EventActor.HARNESS,
            payload={"title": "Advanced"},
        )
    )
    assert recorder.session.current_sequence == 4

    # A late retry of the SAME idempotency key asks for sequence 5, but
    # the store returns the canonical event at sequence 3: it is already
    # covered by the projection and must not roll anything back.
    returned = recorder.append_event(marker(5, "stale-canonical"))

    assert returned.sequence == 3
    assert recorder.session.current_sequence == 4
    stored = stores.events.list_for_session(session_id)
    assert [event.sequence for event in stored] == [0, 1, 2, 3, 4]
    assert len([event for event in stored if event.idempotency_key == "stale-canonical"]) == 1
