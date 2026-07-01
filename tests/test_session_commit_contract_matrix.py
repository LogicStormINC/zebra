from pathlib import Path
from subprocess import run

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_cli.cli import execute


def test_session_commit_contract_matrix_success_replays_from_api_to_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    idempotency_key = "commit-success-1"

    api_response = create_app(database_path).commit_session(
        str(session_id),
        {
            "message": "Commit session changes",
            "author_name": "Zebra Agent",
            "author_email": "zebra-agent@example.local",
        },
        idempotency_key=idempotency_key,
    )
    cli_result = execute(
        [
            "commit",
            str(session_id),
            "--message",
            "Commit session changes",
            "--author-name",
            "Zebra Agent",
            "--author-email",
            "zebra-agent@example.local",
            "--idempotency-key",
            idempotency_key,
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 201
    assert _normalize_api_commit(api_response.body) == _normalize_cli_commit(cli_result.payload)


def test_session_commit_contract_matrix_policy_blocked_replays_from_api_to_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    session_id = _seed_ready_session(
        database_path,
        workspace,
        policy_profile="workspace_write",
    )
    idempotency_key = "commit-policy-1"

    api_response = create_app(database_path).commit_session(
        str(session_id),
        {
            "message": "Blocked commit",
            "author_name": "Zebra Agent",
            "author_email": "zebra-agent@example.local",
        },
        idempotency_key=idempotency_key,
    )
    cli_result = execute(
        [
            "commit",
            str(session_id),
            "--message",
            "Blocked commit",
            "--author-name",
            "Zebra Agent",
            "--author-email",
            "zebra-agent@example.local",
            "--idempotency-key",
            idempotency_key,
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 409
    assert _normalize_api_commit(api_response.body) == _normalize_cli_commit(cli_result.payload)


def test_session_commit_contract_matrix_clean_workspace_replays_from_api_to_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    idempotency_key = "commit-clean-1"

    api_response = create_app(database_path).commit_session(
        str(session_id),
        {
            "message": "No changes",
            "author_name": "Zebra Agent",
            "author_email": "zebra-agent@example.local",
        },
        idempotency_key=idempotency_key,
    )
    cli_result = execute(
        [
            "commit",
            str(session_id),
            "--message",
            "No changes",
            "--author-name",
            "Zebra Agent",
            "--author-email",
            "zebra-agent@example.local",
            "--idempotency-key",
            idempotency_key,
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 409
    assert _normalize_api_commit(api_response.body) == _normalize_cli_commit(cli_result.payload)


def test_session_commit_contract_matrix_missing_session_replays_from_api_to_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = "00000000-0000-0000-0000-000000000001"
    idempotency_key = "commit-missing-1"

    api_response = create_app(database_path).commit_session(
        session_id,
        {
            "message": "Missing session",
            "author_name": "Zebra Agent",
            "author_email": "zebra-agent@example.local",
        },
        idempotency_key=idempotency_key,
    )
    cli_result = execute(
        [
            "commit",
            session_id,
            "--message",
            "Missing session",
            "--author-name",
            "Zebra Agent",
            "--author-email",
            "zebra-agent@example.local",
            "--idempotency-key",
            idempotency_key,
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 404
    assert _normalize_api_commit(api_response.body) == _normalize_cli_commit(cli_result.payload)


def test_session_commit_contract_matrix_success_replays_from_cli_to_api(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    idempotency_key = "commit-success-2"

    cli_result = execute(
        [
            "commit",
            str(session_id),
            "--message",
            "Commit from CLI",
            "--author-name",
            "Zebra Agent",
            "--author-email",
            "zebra-agent@example.local",
            "--idempotency-key",
            idempotency_key,
            "--database",
            str(database_path),
        ]
    )
    api_response = create_app(database_path).commit_session(
        str(session_id),
        {
            "message": "Commit from CLI",
            "author_name": "Zebra Agent",
            "author_email": "zebra-agent@example.local",
        },
        idempotency_key=idempotency_key,
    )

    assert api_response.status_code == 201
    assert _normalize_cli_commit(cli_result.payload) == _normalize_api_commit(api_response.body)


def _normalize_api_commit(payload: dict[str, object]) -> dict[str, object]:
    return payload


def _normalize_cli_commit(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "database"
    }


def _seed_ready_session(
    database_path: Path,
    workspace_root: Path,
    *,
    policy_profile: str,
) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Commit contract matrix",
            user_input="Commit reviewed changes.",
            workspace_root=workspace_root.resolve(),
            policy_profile=policy_profile,
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
