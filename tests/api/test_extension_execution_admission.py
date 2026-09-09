from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_core.application import current_turn
from agent_core.domain.events import EventType
from agent_core.ports.extensions import SkillInstallationPage
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.command_submission import submit_session_command

from tests.agent_security.test_extension_authority import _verified
from tests.api.test_extension_turn_admission import _admission, _AtomicEventStore
from tests.api.test_session_command_routes import _seed_ready_session


@pytest.mark.parametrize("kind", ["run", "resume"])
def test_execution_binds_existing_turn_and_reuses_snapshot(tmp_path: Path, kind: str) -> None:
    database, session_id, revision = _seed_ready_session(tmp_path)
    admission, catalog, snapshots = _admission(2)
    events = _AtomicEventStore(SQLiteEventStore(database))
    stores = SimpleNamespace(events=events, sessions=SQLiteProjectionStore(database))
    before = events.list_for_session(session_id)
    turn = current_turn(before)
    assert turn is not None
    verified = _verified(scopes=["agent.run"])

    def submit(key: str, expected: int):
        return submit_session_command(
            stores,
            str(session_id),
            {"kind": kind, "expected_revision": expected},
            idempotency_key=key,
            extension_admission=admission,
            verified_host_grant=verified,
        )

    assert submit("first", revision).status_code == 202
    _, snapshot = events.bindings[0]
    assert snapshot.turn_id == turn.turn_id
    snapshots.values[(snapshot.scope, snapshot.session_id, snapshot.turn_id)] = snapshot
    catalog.list_skills.return_value = SkillInstallationPage(items=())
    after = events.list_for_session(session_id)
    assert submit("second", after[-1].sequence).status_code == 202
    assert events.bindings[-1][1] == snapshot
    assert catalog.list_skills.await_count == 1
    assert sum(e.event_type is EventType.USER_MESSAGE_RECEIVED for e in after) == sum(
        e.event_type is EventType.USER_MESSAGE_RECEIVED for e in before
    )


def test_execution_without_existing_turn_is_rejected(tmp_path: Path) -> None:
    _, session_id, _ = _seed_ready_session(tmp_path)
    admission, catalog, _ = _admission(2)
    with pytest.raises(ValueError, match="active non-legacy Turn"):
        admission.prepare(
            verified=_verified(scopes=["agent.run"]),
            session_id=session_id,
            events=[],
            client_payload={},
            existing_turn=True,
        )
    catalog.list_skills.assert_not_awaited()
