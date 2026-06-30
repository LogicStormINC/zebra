import base64
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite, StoredArtifactPayload
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_security import PolicyProfile
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteProjectionStore,
    SQLiteToolRunStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_api.app import create_app
from zebra_agent_cli.cli import execute


@pytest.mark.parametrize(
    ("scenario", "policy_profile"),
    [
        ("detail_operator_safe", PolicyProfile.WORKSPACE_WRITE.value),
        ("detail_denied", PolicyProfile.WORKSPACE_WRITE.value),
        ("content_denied", PolicyProfile.WORKSPACE_WRITE.value),
        ("content_unavailable", PolicyProfile.WORKSPACE_WRITE.value),
        ("content_pruned", PolicyProfile.WORKSPACE_WRITE.value),
        ("content_allowed", PolicyProfile.FULL_ACCESS.value),
    ],
)
def test_artifact_access_contract_matrix(
    tmp_path: Path,
    scenario: str,
    policy_profile: str,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, policy_profile)

    if scenario == "detail_operator_safe":
        _seed_payload_backed_tool_artifact(database_path, session.session_id)
        api_response = create_app(database_path).get_session_artifact_detail(
            str(session.session_id),
            "tool-run:5",
        )
        cli_response = execute(
            [
                "artifact",
                "inspect",
                str(session.session_id),
                "tool-run:5",
                "--database",
                str(database_path),
            ]
        ).payload

        assert api_response.status_code == 200
        assert _project_detail_artifact(api_response.body) == _project_detail_artifact(
            cli_response
        )
        return

    if scenario == "detail_denied":
        _seed_payload_backed_tool_artifact(
            database_path,
            session.session_id,
            mime_type="application/json",
            payload=b'{"token":"secret"}',
            output='{"token":"secret"}',
            file_name="result.json",
        )
        api_response = create_app(database_path).get_session_artifact_detail(
            str(session.session_id),
            "tool-run:5",
        )
        cli_response = execute(
            [
                "artifact",
                "inspect",
                str(session.session_id),
                "tool-run:5",
                "--database",
                str(database_path),
            ]
        ).payload

        assert api_response.status_code == 409
        assert _project_access_result(api_response.body) == _project_access_result(cli_response)
        return

    if scenario == "content_denied":
        _seed_payload_backed_tool_artifact(
            database_path,
            session.session_id,
            mime_type="application/json",
            payload=b'{"token":"secret"}',
            output='{"token":"secret"}',
            file_name="result.json",
        )
        api_response = create_app(database_path).get_session_artifact_content(
            str(session.session_id),
            "tool-run:5",
        )
        cli_response = execute(
            [
                "artifact",
                "read",
                str(session.session_id),
                "tool-run:5",
                "--database",
                str(database_path),
            ]
        ).payload

        assert api_response.status_code == 409
        assert _project_access_result(api_response.body) == _project_access_result(cli_response)
        assert cli_response["access"] == {
            "class": "sensitive",
            "required_policy_profile": "full_access",
            "session_policy_profile": "workspace_write",
            "allowed": False,
        }
        return

    if scenario == "content_unavailable":
        stored = _seed_payload_backed_tool_artifact(database_path, session.session_id)
        Path(stored.uri.removeprefix("file://")).unlink()
        api_response = create_app(database_path).get_session_artifact_content(
            str(session.session_id),
            "tool-run:5",
        )
        cli_response = execute(
            [
                "artifact",
                "read",
                str(session.session_id),
                "tool-run:5",
                "--database",
                str(database_path),
            ]
        ).payload

        assert api_response.status_code == 409
        assert _project_access_result(api_response.body) == _project_access_result(cli_response)
        assert cli_response["access"] == {
            "class": "operator_safe",
            "required_policy_profile": "workspace_write",
            "session_policy_profile": "workspace_write",
            "allowed": True,
        }
        return

    if scenario == "content_pruned":
        _seed_payload_backed_tool_artifact(database_path, session.session_id)
        execute(
            [
                "artifact",
                "prune",
                str(session.session_id),
                "tool-run:5",
                "--database",
                str(database_path),
            ]
        )
        api_response = create_app(database_path).get_session_artifact_content(
            str(session.session_id),
            "tool-run:5",
        )
        cli_response = execute(
            [
                "artifact",
                "read",
                str(session.session_id),
                "tool-run:5",
                "--database",
                str(database_path),
            ]
        ).payload

        assert api_response.status_code == 409
        assert _project_access_result(api_response.body) == _project_access_result(cli_response)
        assert cli_response["reason"] == "artifact_payload_pruned"
        return

    _seed_payload_backed_tool_artifact(
        database_path,
        session.session_id,
        mime_type="application/json",
        payload=b'{"token":"secret"}',
        output='{"token":"secret"}',
        file_name="result.json",
    )
    api_response = create_app(database_path).get_session_artifact_content(
        str(session.session_id),
        "tool-run:5",
    )
    cli_response = execute(
        [
            "artifact",
            "read",
            str(session.session_id),
            "tool-run:5",
            "--database",
            str(database_path),
        ]
    ).payload

    assert api_response.status_code == 200
    assert _project_access_result(api_response.body) == _project_access_result(cli_response)
    assert api_response.body["content_base64"] == cli_response["content_base64"]
    assert cli_response["content_base64"] == base64.b64encode(b'{"token":"secret"}').decode(
        "ascii"
    )


def _project_access_result(payload: dict[str, object]) -> dict[str, object]:
    projected = {
        "status": payload["status"],
        "access": payload["access"],
    }
    reason = payload.get("reason")
    if reason is not None:
        projected["reason"] = reason
    return projected


def _project_detail_artifact(payload: dict[str, object]) -> dict[str, object]:
    artifact = payload["artifact"]
    assert isinstance(artifact, dict)
    return {
        "status": payload["status"],
        "artifact": {
            "artifact_id": artifact["artifact_id"],
            "sequence": artifact["sequence"],
            "source": artifact["source"],
            "kind": artifact["kind"],
            "label": artifact["label"],
            "uri": artifact["uri"],
            "preview": artifact["preview"],
            "preview_state": artifact["preview_state"],
            "metadata": artifact["metadata"],
            "retrieval": artifact["retrieval"],
            "lifecycle": artifact["lifecycle"],
            "access": artifact["access"],
        },
    }


def _seed_session(database_path: Path) -> Session:
    return SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Artifact access contract matrix session")
    )


def _seed_payload_backed_tool_artifact(
    database_path: Path,
    session_id: SessionId,
    *,
    mime_type: str = "text/plain",
    payload: bytes = b"pytest passed",
    output: str = "pytest passed",
    file_name: str = "pytest.log",
) -> StoredArtifactPayload:
    stored = SQLiteArtifactPayloadStore(database_path).store_payload(
        ArtifactPayloadWrite(
            session_id=session_id,
            kind="tool_output",
            mime_type=mime_type,
            payload=payload,
            file_name=file_name,
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
            output=output,
            artifact_uri=stored.uri,
            created_at=_created_at(),
        )
    )
    return stored


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
    return datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
