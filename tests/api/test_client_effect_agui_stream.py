"""HTTP replay proof for durable Client Effect AG-UI projection."""

from datetime import UTC, datetime
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_event_id
from agent_integrations.ag_ui import AgUiCursor
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
    sqlite_control_plane_stores,
)
from fastapi.testclient import TestClient
from zebra_agent_api.http import create_http_app


def test_client_effect_replays_once_then_terminal_cursor_only_removes_it(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "client-effect.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Client effect replay",
            user_input="Open the item.",
            workspace_root=tmp_path.resolve(),
        )
    )
    store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        rebuild_workspace(list(bootstrap.events))
    )
    sequence = bootstrap.session.current_sequence + 1
    scheduled = _append(
        store,
        bootstrap.session.session_id,
        sequence,
        EventType.CLIENT_EFFECT_SCHEDULED,
        {
            "attempt_number": 1,
            "tool_name": "app.ui.item.open",
            "tool_call_id": "call-1",
            "client_effect_id": "effect-1",
            "action_name": "app.ui.item.open",
            "arguments": {"itemId": "item-1"},
            "action_contract_digest": "a" * 64,
            "client_binding_digest": "b" * 64,
            "expected_ui_revision": 3,
            "idempotency_key": "client-effect:effect-1",
            "request_digest": "c" * 64,
        },
    )
    _append(
        store,
        bootstrap.session.session_id,
        sequence + 1,
        EventType.CLIENT_EFFECT_RECEIPT_ACCEPTED,
        {
            "client_effect_id": "effect-1",
            "receipt_id": "receipt-1",
            "status": "succeeded",
            "request_digest": "c" * 64,
        },
    )
    _append(
        store,
        bootstrap.session.session_id,
        sequence + 2,
        EventType.SESSION_COMPLETED,
        {},
    )
    client = TestClient(
        create_http_app(database_path, stores=sqlite_control_plane_stores(database_path))
    )
    path = f"/agui/threads/{bootstrap.session.session_id}/runs/run-client/stream"

    initial = client.get(path)

    assert initial.status_code == 200
    assert '"path":"/zebra/clientEffects/effect-1"' in initial.text
    assert '"execution_location":"client"' in initial.text
    assert '"action_contract_digest":"' + ("a" * 64) + '"' in initial.text
    cursor = _cursor_for_sequence(initial.text, scheduled.sequence)
    assert cursor is not None

    replay = client.get(f"{path}?cursor={cursor}")

    assert replay.status_code == 200
    assert '"op":"remove"' in replay.text
    assert '"op":"add"' not in replay.text


def _append(
    store: SQLiteEventStore,
    session_id,
    sequence: int,
    event_type: EventType,
    payload: dict[str, object],
) -> SessionEvent:
    event = SessionEvent(
        event_id=new_event_id(),
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        payload=payload,
        actor=EventActor.HARNESS,
        created_at=datetime.now(UTC),
    )
    store.append(event)
    return event


def _cursor_for_sequence(text: str, sequence: int) -> str | None:
    for block in text.split("\n\n"):
        first = block.splitlines()[0] if block.splitlines() else ""
        if not first.startswith("id: "):
            continue
        cursor = AgUiCursor.decode(first.removeprefix("id: "))
        if cursor.sequence == sequence:
            return first.removeprefix("id: ")
    return None
