from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_cli.cli import execute


def _finish_first_turn(database_path: Path, session_id: str) -> None:
    """Close bootstrap Turn 0 so a follow-up message can be admitted."""
    from uuid import UUID

    from agent_core.application import current_turn
    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.identifiers import SessionId
    from agent_core.domain.turns import derive_turn_id
    from agent_storage import SQLiteEventStore as _Store
    from agent_storage import SQLiteProjectionStore as _Proj

    key = SessionId(UUID(str(session_id)))
    event_store = _Store(database_path)
    events = event_store.list_for_session(key)
    session = events[0].session_id
    open_turn = current_turn(events)
    turn_id = (
        open_turn.turn_id if open_turn else str(derive_turn_id(session, 0))
    )
    turn_index = open_turn.turn_index if open_turn else 0
    base = events[-1].sequence
    event_store.append(
        SessionEvent.create(
            session_id=session,
            sequence=base + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session,
            sequence=base + 2,
            event_type=EventType.TURN_COMPLETED,
            actor=EventActor.HARNESS,
            payload={
                "turn_id": turn_id,
                "turn_index": turn_index,
                "closes_segment": False,
            },
        )
    )
    _Proj(database_path).save_session(
        rebuild_session(event_store.list_for_session(key))
    )



def test_session_message_append_contract_matrix_appended_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    api_database_path = tmp_path / "api-append.sqlite"
    api_session_id = _seed_ready_session(api_database_path, workspace_root=tmp_path)
    _finish_first_turn(api_database_path, api_session_id)
    cli_database_path = tmp_path / "cli-append.sqlite"
    cli_session_id = _seed_ready_session(
        cli_database_path,
        workspace_root=tmp_path,
        session_id=api_session_id,
    )
    _finish_first_turn(cli_database_path, cli_session_id)

    api_response = create_app(api_database_path).append_session_message(
        api_session_id,
        {"content": "Please continue from the latest checkpoint."},
    )
    cli_result = execute(
        [
            "message",
            cli_session_id,
            "--content",
            "Please continue from the latest checkpoint.",
            "--database",
            str(cli_database_path),
        ]
    )

    assert api_response.status_code == 201
    assert _normalize_api_append_result(
        api_response.body
    ) == _normalize_cli_append_result(cli_result.payload)


def test_session_message_append_contract_matrix_invalid_request_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "invalid.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)

    api_response = create_app(database_path).append_session_message(
        session_id,
        {"content": "   "},
    )
    cli_result = execute(
        [
            "message",
            session_id,
            "--content",
            "   ",
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 400
    assert _normalize_api_append_result(
        api_response.body
    ) == _normalize_cli_append_result(cli_result.payload)


def test_session_message_append_contract_matrix_missing_session_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "missing.sqlite"
    session_id = "00000000-0000-0000-0000-000000000001"

    api_response = create_app(database_path).append_session_message(
        session_id,
        {"content": "Continue."},
    )
    cli_result = execute(
        [
            "message",
            session_id,
            "--content",
            "Continue.",
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 404
    assert _normalize_api_append_result(
        api_response.body
    ) == _normalize_cli_append_result(cli_result.payload)


def test_session_message_append_contract_matrix_terminal_session_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "terminal.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Terminal message").model_copy(
            update={"status": SessionStatus.COMPLETED}
        )
    )

    api_response = create_app(database_path).append_session_message(
        str(session.session_id),
        {"content": "Try again."},
    )
    cli_result = execute(
        [
            "message",
            str(session.session_id),
            "--content",
            "Try again.",
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 409
    assert _normalize_api_append_result(
        api_response.body
    ) == _normalize_cli_append_result(cli_result.payload)


def _normalize_api_append_result(payload: dict[str, object]) -> dict[str, object]:
    return payload


def _normalize_cli_append_result(payload: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if key != "database"}


def _seed_ready_session(
    database_path: Path,
    *,
    workspace_root: Path,
    session_id: str | None = None,
) -> str:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Append contract",
            user_input="Inspect and continue.",
            workspace_root=workspace_root.resolve(),
        )
    )
    session = bootstrap.session
    events = bootstrap.events
    if session_id is not None:
        session = session.model_copy(update={"session_id": session_id})
        events = tuple(
            event.model_copy(update={"session_id": session.session_id})
            for event in bootstrap.events
        )

    event_store = SQLiteEventStore(database_path)
    for event in events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(session)
    return str(session.session_id)
