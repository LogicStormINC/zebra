from pathlib import Path
from subprocess import run

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_cli.cli import execute


def test_session_diff_contract_matrix_dirty_workspace_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace)

    api_response = create_app(database_path).get_session_diff(str(session_id))
    cli_result = execute(["diff", str(session_id), "--database", str(database_path)])

    assert api_response.status_code == 200
    assert _normalize_api_diff(api_response.body) == _normalize_cli_diff(cli_result.payload)


def test_session_diff_contract_matrix_clean_workspace_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace)

    api_response = create_app(database_path).get_session_diff(str(session_id))
    cli_result = execute(["diff", str(session_id), "--database", str(database_path)])

    assert api_response.status_code == 200
    assert _normalize_api_diff(api_response.body) == _normalize_cli_diff(cli_result.payload)


def test_session_diff_contract_matrix_missing_session_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = "00000000-0000-0000-0000-000000000001"

    api_response = create_app(database_path).get_session_diff(session_id)
    cli_result = execute(["diff", session_id, "--database", str(database_path)])

    assert api_response.status_code == 404
    assert _normalize_api_diff(api_response.body) == _normalize_cli_diff(cli_result.payload)


def test_session_diff_contract_matrix_non_git_workspace_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "not-git"
    workspace.mkdir()
    session_id = _seed_ready_session(database_path, workspace)

    api_response = create_app(database_path).get_session_diff(str(session_id))
    cli_result = execute(["diff", str(session_id), "--database", str(database_path)])

    assert api_response.status_code == 409
    assert _normalize_api_diff(api_response.body) == _normalize_cli_diff(cli_result.payload)


def _normalize_api_diff(payload: dict[str, object]) -> dict[str, object]:
    status = payload.get("status")
    if status == "not_found":
        return {
            "session_id": payload["session_id"],
            "status": "not_found",
        }
    if status == "diff_unavailable":
        return {
            "session_id": payload["session_id"],
            "status": "diff_unavailable",
            "reason": payload["reason"],
        }
    return {
        "session_id": payload["session_id"],
        "status": "ok",
        "workspace": payload["workspace"],
        "clean": payload["clean"],
        "git_status": payload["git_status"],
        "diff": payload["diff"],
    }


def _normalize_cli_diff(payload: dict[str, object]) -> dict[str, object]:
    status = payload.get("status")
    if status == "not_found":
        return {
            "session_id": payload["session_id"],
            "status": "not_found",
        }
    if status == "diff_unavailable":
        return {
            "session_id": payload["session_id"],
            "status": "diff_unavailable",
            "reason": payload["reason"],
        }
    return {
        "session_id": payload["session_id"],
        "status": "ok",
        "workspace": payload["workspace"],
        "clean": payload["clean"],
        "git_status": payload["git_status"],
        "diff": payload["diff"],
    }


def _seed_ready_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Diff contract matrix",
            user_input="Inspect session diff.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id


def _git_workspace(path: Path) -> Path:
    path.mkdir()
    run(("git", "init"), cwd=path, check=True, capture_output=True, text=True)
    run(
        ("git", "config", "user.name", "Zebra Agent"),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    run(
        ("git", "config", "user.email", "zebra@example.com"),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    (path / "tracked.txt").write_text("initial\n", encoding="utf-8")
    run(("git", "add", "tracked.txt"), cwd=path, check=True, capture_output=True, text=True)
    run(("git", "commit", "-m", "init"), cwd=path, check=True, capture_output=True, text=True)
    return path.resolve()
