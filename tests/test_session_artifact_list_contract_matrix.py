from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.identifiers import SessionId
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.sessions import Session
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_security import PolicyProfile
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteModelCallStore,
    SQLiteProjectionStore,
    SQLiteToolRunStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_api.app import create_app
from zebra_agent_cli.cli import execute


def test_session_artifact_list_contract_matrix_non_empty_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "artifacts.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.WORKSPACE_WRITE.value)
    _seed_indexed_artifact(database_path, session.session_id)
    _seed_payload_backed_artifact(database_path, session.session_id)

    api_response = create_app(database_path).get_session_artifacts(str(session.session_id))
    cli_result = execute(
        ["artifact", "list", str(session.session_id), "--database", str(database_path)]
    )

    assert api_response.status_code == 200
    assert _normalize_api_artifact_list(
        api_response.body
    ) == _normalize_cli_artifact_list(cli_result.payload)


def test_session_artifact_list_contract_matrix_empty_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "empty.sqlite"
    session = _seed_session(database_path)

    api_response = create_app(database_path).get_session_artifacts(str(session.session_id))
    cli_result = execute(
        ["artifact", "list", str(session.session_id), "--database", str(database_path)]
    )

    assert api_response.status_code == 200
    assert _normalize_api_artifact_list(
        api_response.body
    ) == _normalize_cli_artifact_list(cli_result.payload)


def test_session_artifact_list_contract_matrix_missing_session_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "missing.sqlite"
    session_id = "00000000-0000-0000-0000-000000000001"

    api_response = create_app(database_path).get_session_artifacts(session_id)
    cli_result = execute(["artifact", "list", session_id, "--database", str(database_path)])

    assert api_response.status_code == 404
    assert _normalize_api_artifact_list(
        api_response.body
    ) == _normalize_cli_artifact_list(cli_result.payload)


def _normalize_api_artifact_list(payload: dict[str, object]) -> dict[str, object]:
    return payload


def _normalize_cli_artifact_list(payload: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if key != "database"}


def _seed_session(database_path: Path) -> Session:
    return SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Artifact list contract matrix")
    )


def _seed_indexed_artifact(database_path: Path, session_id: SessionId) -> None:
    SQLiteModelCallStore(database_path).upsert(
        ModelCallRecord(
            session_id=session_id,
            sequence=4,
            provider="deepseek",
            model_name="deepseek-v4-flash",
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            latency_ms=250,
            cache_hit=False,
            cost_usd=0.001,
            assistant_message="Summarized the repository.",
            tool_call_count=1,
            created_at=_created_at(),
        )
    )


def _seed_payload_backed_artifact(database_path: Path, session_id: SessionId) -> None:
    stored = SQLiteArtifactPayloadStore(database_path).store_payload(
        ArtifactPayloadWrite(
            session_id=session_id,
            kind="tool_output",
            mime_type="text/plain",
            payload=b"pytest passed",
            file_name="pytest.log",
            created_at=_created_at(),
        )
    )
    SQLiteToolRunStore(database_path).upsert(
        ToolRunRecord(
            session_id=session_id,
            sequence=5,
            tool_name="tests.run",
            status="executed",
            idempotency_key="tool-5",
            output="pytest passed",
            artifact_uri=stored.uri,
            created_at=_created_at(),
        )
    )


def _seed_workspace_policy(
    database_path: Path,
    session_id: SessionId,
    policy_profile: str,
) -> None:
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        WorkspaceProjection(
            session_id=session_id,
            workspace_root="/tmp/workspace",
            prepared_at=_created_at(),
            updated_at=_created_at(),
            current_sequence=1,
            status=WorkspaceStatus.PREPARED,
            policy_profile=policy_profile,
        )
    )


def _created_at() -> datetime:
    return datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
