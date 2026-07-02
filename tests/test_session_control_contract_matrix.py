from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.workspaces import WorkspaceStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore, SQLiteWorkspaceProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_cli.cli import execute


def test_session_control_contract_matrix_cancelled_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    api_database_path = tmp_path / "api-cancel.sqlite"
    api_session_id = _seed_ready_session(api_database_path, workspace_root=tmp_path)
    cli_database_path = tmp_path / "cli-cancel.sqlite"
    cli_session_id = _seed_ready_session(
        cli_database_path,
        workspace_root=tmp_path,
        session_id=api_session_id,
    )

    api_response = create_app(api_database_path).cancel_session(api_session_id, {})
    cli_result = execute(
        ["cancel", cli_session_id, "--database", str(cli_database_path)]
    )

    assert api_response.status_code == 200
    assert _normalize_api_control_result(
        api_response.body
    ) == _normalize_cli_control_result(cli_result.payload)


def test_session_control_contract_matrix_cancel_invalid_state_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "cancel-terminal.sqlite"
    session_id = _seed_terminal_session(database_path, workspace_root=tmp_path)

    api_response = create_app(database_path).cancel_session(session_id, {})
    cli_result = execute(["cancel", session_id, "--database", str(database_path)])

    assert api_response.status_code == 409
    assert _normalize_api_control_result(
        api_response.body
    ) == _normalize_cli_control_result(cli_result.payload)


def test_session_control_contract_matrix_cancel_missing_session_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "cancel-missing.sqlite"
    session_id = "00000000-0000-0000-0000-000000000001"

    api_response = create_app(database_path).cancel_session(session_id, {})
    cli_result = execute(["cancel", session_id, "--database", str(database_path)])

    assert api_response.status_code == 404
    assert _normalize_api_control_result(
        api_response.body
    ) == _normalize_cli_control_result(cli_result.payload)


def test_session_control_contract_matrix_suspend_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    api_database_path = tmp_path / "api-suspend.sqlite"
    api_session_id = _seed_ready_session(api_database_path, workspace_root=tmp_path)
    cli_database_path = tmp_path / "cli-suspend.sqlite"
    cli_session_id = _seed_ready_session(
        cli_database_path,
        workspace_root=tmp_path,
        session_id=api_session_id,
    )

    api_response = create_app(api_database_path).suspend_session(api_session_id, {})
    cli_result = execute(
        ["suspend", cli_session_id, "--database", str(cli_database_path)]
    )

    assert api_response.status_code == 200
    assert _normalize_api_control_result(
        api_response.body
    ) == _normalize_cli_control_result(cli_result.payload)


def test_session_control_contract_matrix_suspend_invalid_state_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "suspend-terminal.sqlite"
    session_id = _seed_terminal_session(database_path, workspace_root=tmp_path)

    api_response = create_app(database_path).suspend_session(session_id, {})
    cli_result = execute(["suspend", session_id, "--database", str(database_path)])

    assert api_response.status_code == 409
    assert _normalize_api_control_result(
        api_response.body
    ) == _normalize_cli_control_result(cli_result.payload)


def test_session_control_contract_matrix_suspend_missing_session_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "suspend-missing.sqlite"
    session_id = "00000000-0000-0000-0000-000000000001"

    api_response = create_app(database_path).suspend_session(session_id, {})
    cli_result = execute(["suspend", session_id, "--database", str(database_path)])

    assert api_response.status_code == 404
    assert _normalize_api_control_result(
        api_response.body
    ) == _normalize_cli_control_result(cli_result.payload)


def _normalize_api_control_result(payload: dict[str, object]) -> dict[str, object]:
    if payload.get("status") == "suspended" and "snapshot_id" in payload:
        return {
            key: value
            for key, value in payload.items()
            if key != "snapshot_id"
        }
    return payload


def _normalize_cli_control_result(payload: dict[str, object]) -> dict[str, object]:
    ignored_keys = {"database"}
    if payload.get("status") == "suspended" and "snapshot_id" in payload:
        ignored_keys.add("snapshot_id")
    return {
        key: value
        for key, value in payload.items()
        if key not in ignored_keys
    }


def _seed_ready_session(
    database_path: Path,
    *,
    workspace_root: Path,
    session_id: str | None = None,
) -> str:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Control contract",
            user_input="Inspect and continue.",
            workspace_root=workspace_root.resolve(),
        )
    )
    session = bootstrap.session
    events = bootstrap.events
    if session_id is not None:
        stable_session_id = SessionId(UUID(session_id))
        session = session.model_copy(update={"session_id": stable_session_id})
        events = tuple(
            event.model_copy(update={"session_id": session.session_id})
            for event in bootstrap.events
        )

    event_store = SQLiteEventStore(database_path)
    for event in events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(rebuild_workspace(list(events)))
    return str(session.session_id)


def _seed_terminal_session(
    database_path: Path,
    *,
    workspace_root: Path,
) -> str:
    session_id = _seed_ready_session(database_path, workspace_root=workspace_root)
    projection_store = SQLiteProjectionStore(database_path)
    session = projection_store.get_session(session_id)
    assert session is not None
    projection_store.save_session(session.model_copy(update={"status": SessionStatus.COMPLETED}))
    workspace_store = SQLiteWorkspaceProjectionStore(database_path)
    workspace = workspace_store.get_workspace(session_id)
    assert workspace is not None
    workspace_store.save_workspace(
        workspace.model_copy(update={"status": WorkspaceStatus.COMPLETED})
    )
    return session_id
