import base64
from datetime import UTC, datetime
from pathlib import Path

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
from zebra_agent_cli.cli import execute


def test_cli_artifact_inspect_includes_access_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.WORKSPACE_WRITE.value)
    _seed_payload_backed_tool_artifact(database_path, session.session_id)

    result = execute(
        [
            "artifact",
            "inspect",
            str(session.session_id),
            "tool-run:5",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload["artifact"]["access"] == {
        "class": "operator_safe",
        "required_policy_profile": "workspace_write",
        "session_policy_profile": "workspace_write",
        "allowed": True,
    }


def test_cli_artifact_read_denied_includes_access_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.WORKSPACE_WRITE.value)
    _seed_payload_backed_tool_artifact(
        database_path,
        session.session_id,
        mime_type="application/json",
        payload=b'{"token":"secret"}',
        output='{"token":"secret"}',
        file_name="result.json",
    )

    result = execute(
        [
            "artifact",
            "read",
            str(session.session_id),
            "tool-run:5",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload["status"] == "artifact_access_denied"
    assert result.payload["access"] == {
        "class": "sensitive",
        "required_policy_profile": "full_access",
        "session_policy_profile": "workspace_write",
        "allowed": False,
    }


def test_cli_artifact_read_ok_includes_access_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.FULL_ACCESS.value)
    _seed_payload_backed_tool_artifact(
        database_path,
        session.session_id,
        mime_type="application/json",
        payload=b'{"token":"secret"}',
        output='{"token":"secret"}',
        file_name="result.json",
    )

    result = execute(
        [
            "artifact",
            "read",
            str(session.session_id),
            "tool-run:5",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload["status"] == "ok"
    assert result.payload["access"] == {
        "class": "sensitive",
        "required_policy_profile": "full_access",
        "session_policy_profile": "full_access",
        "allowed": True,
    }
    assert result.payload["content_base64"] == base64.b64encode(b'{"token":"secret"}').decode(
        "ascii"
    )


def test_cli_artifact_unavailable_includes_access_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.WORKSPACE_WRITE.value)
    stored = _seed_payload_backed_tool_artifact(database_path, session.session_id)
    Path(stored.uri.removeprefix("file://")).unlink()

    result = execute(
        [
            "artifact",
            "read",
            str(session.session_id),
            "tool-run:5",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload["status"] == "artifact_unavailable"
    assert result.payload["reason"] == "artifact_payload_missing"
    assert result.payload["access"] == {
        "class": "operator_safe",
        "required_policy_profile": "workspace_write",
        "session_policy_profile": "workspace_write",
        "allowed": True,
    }


def _seed_session(database_path: Path) -> Session:
    return SQLiteProjectionStore(database_path).save_session(
        Session.create(title="CLI artifact access explainability session")
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
