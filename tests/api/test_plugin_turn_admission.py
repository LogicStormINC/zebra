"""Explicit request absence and empty selection have different authority meaning."""

from pathlib import Path

from agent_storage import SQLiteEventStore

from tests.agent_security.test_extension_authority import _verified
from tests.api.test_extension_turn_admission import _admission
from tests.api.test_session_command_routes import _seed_ready_session


def test_explicit_empty_selects_no_ceiling_skills(tmp_path: Path) -> None:
    _, session_id, _ = _seed_ready_session(tmp_path)
    admission, store, _ = _admission(3)
    events = SQLiteEventStore(tmp_path / "sessions.sqlite").list_for_session(session_id)
    _, legacy, _ = admission.prepare(
        verified=_verified(scopes=["agent.run"]),
        session_id=session_id,
        events=events,
        client_payload={"content": "go"},
    )
    _, empty, _ = admission.prepare(
        verified=_verified(scopes=["agent.run"]),
        session_id=session_id,
        events=events,
        client_payload={"content": "go", "extension_selection": {}},
    )
    assert legacy.skills and not empty.skills and not empty.mcp
