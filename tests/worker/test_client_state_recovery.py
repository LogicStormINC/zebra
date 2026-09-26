"""Durable AG-UI Client State survives Worker restart from the command event."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_storage import SQLiteEventStore
from zebra_agent_worker.task_recovery import recover_client_state_evidence


def _event(
    *,
    digest: str | None = None,
    session_id: SessionId | None = None,
    sequence: int = 0,
    state: dict[str, object] | None = None,
) -> SessionEvent:
    session_id = session_id or new_session_id()
    state = (
        {"trench.ui.route": {"pathname": "/dashboard/strategy"}}
        if state is None
        else state
    )
    state_digest = sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    command = SessionCommand(
        session_id=session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=0,
        idempotency_key="agui-client-state-1",
        payload={
            "thread_id": "task-1",
            "run_id": "run-1",
            "client": {
                "client_session_id": "11111111-1111-4111-8111-111111111111",
                "frontend_app_id": "trench-web",
                "profile_digest": "a" * 64,
                "ui_revision": 7,
                "state_snapshot": state,
                "state_digest": digest or state_digest,
                "redacted_keys": [],
            },
        },
    )
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
        created_at=datetime.now(UTC),
    )


def test_client_state_recovers_from_the_durable_command() -> None:
    evidence = recover_client_state_evidence([_event()])

    assert evidence is not None
    assert evidence.kind == "client_state"
    assert evidence.metadata is not None
    assert evidence.metadata["ui_revision"] == 7
    assert evidence.metadata["state"] == {"trench.ui.route": {"pathname": "/dashboard/strategy"}}


def test_client_state_recovery_rejects_digest_drift() -> None:
    with pytest.raises(ValueError, match="digest"):
        recover_client_state_evidence([_event(digest="b" * 64)])


def test_no_client_state_remains_a_supported_headless_path() -> None:
    assert recover_client_state_evidence([]) is None


def test_latest_empty_state_survives_store_reopen_without_reviving_stale_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "client-state.db"
    session_id = new_session_id()
    store = SQLiteEventStore(database)
    store.append(_event(session_id=session_id))
    store.append(_event(session_id=session_id, sequence=1, state={}))

    # Re-open the durable store to model a new Worker process after restart.
    recovered_events = SQLiteEventStore(database).list_for_session(session_id)
    evidence = recover_client_state_evidence(recovered_events)

    assert evidence is not None
    assert evidence.metadata is not None
    assert evidence.metadata["state"] == {}
