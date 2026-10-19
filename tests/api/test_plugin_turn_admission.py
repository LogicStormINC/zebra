"""Explicit request absence and empty selection have different authority meaning."""

from pathlib import Path

import pytest
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


def test_explicit_mcp_uses_exact_lookup_and_empty_reads_nothing() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from zebra_agent_api.extension_mcp_selection import select_enabled_mcp

    from tests.agent_storage.test_postgres_plugin_installations import SCOPE, _catalog, _record

    async def check():
        store, catalogs = AsyncMock(), AsyncMock()
        assert await select_enabled_mcp(store, catalogs, SCOPE, ()) == ()
        assert not store.mock_calls and not catalogs.mock_calls
        connection = _record().bindings[0].connection
        store.get_mcp.return_value = connection
        catalogs.latest.return_value = _catalog(connection)
        selected = await select_enabled_mcp(store, catalogs, SCOPE, (connection.connection_id,))
        assert selected[0].connection == connection
        store.list_mcp.assert_not_called()
        store.get_mcp.assert_awaited_once_with(scope=SCOPE, connection_id=connection.connection_id)

    asyncio.run(check())


def test_disabled_selection_refuses_before_command_append(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from agent_storage import SQLiteProjectionStore
    from zebra_agent_api.command_submission import submit_session_command

    from tests.api.test_extension_turn_admission import _AtomicEventStore

    database, session_id, revision = _seed_ready_session(tmp_path)
    admission, _, _ = _admission()
    stores = SimpleNamespace(
        events=_AtomicEventStore(SQLiteEventStore(database)),
        sessions=SQLiteProjectionStore(database),
    )
    payload = {
        "kind": "message",
        "expected_revision": revision,
        "payload": {
            "content": "go",
            "extension_selection": {"plugins": [{"installation_id": "plugin-a", "revision": 1}]},
        },
    }
    for configured, status in ((None, 400), (admission, 409)):
        response = submit_session_command(
            stores,
            str(session_id),
            payload,
            idempotency_key="plugin-off",
            extension_admission=configured,
            verified_host_grant=_verified(scopes=["agent.run"]),
        )
        assert response.status_code == status
    assert stores.events.bindings == []


@pytest.mark.parametrize("legacy", [False, True])
def test_same_turn_rejects_changed_explicit_selection_without_resolving_latest(
    tmp_path: Path,
    legacy: bool,
) -> None:
    import pytest
    from agent_core.contracts import SessionCommand, SessionCommandKind
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.extension_snapshots import ExtensionSnapshot
    from agent_security.extension_authority import extension_runtime_scope_from_grant
    from zebra_agent_api.extension_turn_admission import ClientExtensionBindingError

    database, session_id, _ = _seed_ready_session(tmp_path)
    admission, store, snapshots = _admission(2)
    verified = _verified(scopes=["agent.run"])
    scope = extension_runtime_scope_from_grant(verified)
    events = SQLiteEventStore(database).list_for_session(session_id)
    turn_id = events[1].payload["turn_id"]
    snapshot = ExtensionSnapshot(
        scope=scope,
        session_id=str(session_id),
        turn_id=turn_id,
        skills=(store.list_skills.return_value.items[1],),
        direct_skills=() if legacy else ("install-01",),
    )
    snapshots.values[(scope, str(session_id), turn_id)] = snapshot
    command = SessionCommand(
        session_id=session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=events[-1].sequence,
        idempotency_key="prior-run",
        payload={},
    )
    events.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=events[-1].sequence + 1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.USER,
            payload=command.event_payload(
                extension_snapshot_digest=snapshot.digest, extension_turn_id=turn_id
            ),
            idempotency_key=command.idempotency_key,
        )
    )
    with pytest.raises(ClientExtensionBindingError, match="conflicts"):
        admission.prepare(
            verified=verified,
            session_id=session_id,
            events=events,
            client_payload={"extension_selection": {}},
            existing_turn=True,
        )
    _, restored, _ = admission.prepare(
        verified=verified,
        session_id=session_id,
        events=events,
        client_payload={},
        existing_turn=True,
    )
    assert restored == snapshot
    store.list_skills.assert_not_called()
