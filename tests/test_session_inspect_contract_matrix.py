from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_storage import SQLiteProjectionStore, SQLiteWorkspaceProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_cli.cli import execute


def test_session_inspect_contract_matrix_populated_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "session-inspect.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Inspect parity").model_copy(
            update={
                "status": SessionStatus.WAITING_APPROVAL,
                "current_sequence": 4,
                "approval_context": ApprovalContext(
                    tool_name="mcp.github.create_pr",
                    reason="Approval required before opening a pull request.",
                    policy_profile="workspace_write",
                    route="mcp_proxy",
                    target="github",
                    network_profile="domain-allowlist",
                    scope=("pull_requests:write",),
                ),
            }
        )
    )
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        WorkspaceProjection.model_validate(
            {
                "session_id": session.session_id,
                "workspace_root": str(tmp_path.resolve()),
                "prepared_at": _created_at(),
                "updated_at": _created_at(),
                "current_sequence": 4,
                "status": WorkspaceStatus.SUSPENDED,
                "runtime_name": "gvisor",
                "runtime_engine": "docker",
                "runtime_image": "zebra/runtime@sha256:" + "a" * 64,
                "runtime_spec_digest": "b" * 64,
                "runtime_network_enforcement": "container-network-none",
                "runtime_workspace_writable": True,
                "snapshot_id": "snap-inspect-1",
                "snapshot_path": "/tmp/zebra-agent-runtime/snap-inspect-1",
            }
        )
    )

    api_response = create_app(database_path).get_session(str(session.session_id))
    cli_result = execute(["inspect", str(session.session_id), "--database", str(database_path)])

    assert api_response.status_code == 200
    assert _normalize_api_inspect(api_response.body) == _normalize_cli_inspect(cli_result.payload)
    assert api_response.body["workspace"]["runtime"]["class"] == "gvisor"


def test_session_inspect_contract_matrix_missing_session_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "missing.sqlite"
    session_id = "00000000-0000-0000-0000-000000000001"

    api_response = create_app(database_path).get_session(session_id)
    cli_result = execute(["inspect", session_id, "--database", str(database_path)])

    assert api_response.status_code == 404
    assert _normalize_api_inspect(api_response.body) == _normalize_cli_inspect(cli_result.payload)


def _normalize_api_inspect(payload: dict[str, object]) -> dict[str, object]:
    return payload


def _normalize_cli_inspect(payload: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if key != "database"}


def _created_at() -> datetime:
    return datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
