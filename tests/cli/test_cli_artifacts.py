import base64
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
from zebra_agent_cli.cli import execute


def test_cli_artifact_list_returns_indexed_artifacts(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.WORKSPACE_WRITE.value)
    _seed_indexed_artifacts(database_path, session.session_id)
    _seed_payload_backed_tool_artifact(database_path, session.session_id)

    result = execute(
        [
            "artifact",
            "list",
            str(session.session_id),
            "--database",
            str(database_path),
        ]
    )

    assert result.command == "artifact"
    assert result.payload["session_id"] == str(session.session_id)
    assert result.payload["database"] == str(database_path)
    assert [artifact["artifact_id"] for artifact in result.payload["artifacts"]] == [
        "model-call:4",
        "tool-run:5",
    ]
    assert result.payload["artifacts"][0]["retrieval"] == {
        "status": "indexed_only",
        "retrievable": False,
        "uri": None,
    }
    assert result.payload["artifacts"][0]["access"] == {
        "class": "operator_safe",
        "required_policy_profile": "workspace_write",
        "session_policy_profile": "workspace_write",
        "allowed": True,
    }
    assert result.payload["artifacts"][1]["retrieval"] == {
        "status": "payload_available",
        "retrievable": True,
        "uri": result.payload["artifacts"][1]["uri"],
    }


def test_cli_artifact_list_returns_empty_list(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)

    result = execute(
        [
            "artifact",
            "list",
            str(session.session_id),
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": str(session.session_id),
        "database": str(database_path),
        "artifacts": [],
    }


def test_cli_artifact_list_returns_not_found_for_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "artifact",
            "list",
            "00000000-0000-0000-0000-000000000000",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": "00000000-0000-0000-0000-000000000000",
        "database": str(database_path),
        "status": "not_found",
    }


def test_cli_artifact_inspect_reports_payload_backed_retrieval(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    payload = _seed_payload_backed_tool_artifact(database_path, session.session_id)

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

    assert result.command == "artifact"
    assert result.payload["status"] == "ok"
    assert result.payload["artifact"]["preview_state"] == {
        "redacted": False,
        "truncated": False,
    }
    assert result.payload["artifact"]["retrieval"] == {
        "status": "payload_available",
        "retrievable": True,
        "uri": payload.uri,
    }
    assert result.payload["artifact"]["lifecycle"] == {
        "status": "active",
        "retained_until": None,
        "pruned_at": None,
        "expired": False,
    }


def test_cli_artifact_inspect_reports_indexed_only_artifact(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_indexed_artifacts(database_path, session.session_id)

    result = execute(
        [
            "artifact",
            "inspect",
            str(session.session_id),
            "model-call:4",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload["artifact"]["retrieval"] == {
        "status": "indexed_only",
        "retrievable": False,
        "uri": None,
    }
    assert result.payload["artifact"]["preview_state"] == {
        "redacted": False,
        "truncated": False,
    }
    assert result.payload["artifact"]["lifecycle"] is None


def test_cli_artifact_read_returns_base64_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_payload_backed_tool_artifact(database_path, session.session_id)

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

    assert result.payload == {
        "session_id": str(session.session_id),
        "artifact_id": "tool-run:5",
        "database": str(database_path),
        "status": "ok",
        "access": {
            "class": "operator_safe",
            "required_policy_profile": "workspace_write",
            "session_policy_profile": "workspace_write",
            "allowed": True,
        },
        "encoding": "base64",
        "content_base64": base64.b64encode(b"pytest passed").decode("ascii"),
        "size_bytes": 13,
    }


def test_cli_artifact_read_reports_missing_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    payload = _seed_payload_backed_tool_artifact(database_path, session.session_id)
    # CTX-ART-02: access_uri holds the volatile file:// path.
    assert payload.access_uri is not None
    Path(payload.access_uri.removeprefix("file://")).unlink()

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

    assert result.payload == {
        "session_id": str(session.session_id),
        "artifact_id": "tool-run:5",
        "database": str(database_path),
        "status": "artifact_unavailable",
        "reason": "artifact_payload_missing",
        "access": {
            "class": "operator_safe",
            "required_policy_profile": "workspace_write",
            "session_policy_profile": "workspace_write",
            "allowed": True,
        },
    }


def test_cli_artifact_read_reports_pruned_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.WORKSPACE_WRITE.value)
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

    assert result.payload == {
        "session_id": str(session.session_id),
        "artifact_id": "tool-run:5",
        "database": str(database_path),
        "status": "artifact_unavailable",
        "reason": "artifact_payload_pruned",
        "access": {
            "class": "operator_safe",
            "required_policy_profile": "workspace_write",
            "session_policy_profile": "workspace_write",
            "allowed": True,
        },
    }


def test_cli_artifact_inspect_denies_sensitive_payload_for_workspace_write(
    tmp_path: Path,
) -> None:
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
            "inspect",
            str(session.session_id),
            "tool-run:5",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": str(session.session_id),
        "artifact_id": "tool-run:5",
        "database": str(database_path),
        "status": "artifact_access_denied",
        "reason": "artifact_read_requires_full_access_policy",
        "access": {
            "class": "sensitive",
            "required_policy_profile": "full_access",
            "session_policy_profile": "workspace_write",
            "allowed": False,
        },
    }


def test_cli_artifact_read_denies_sensitive_payload_for_workspace_write(
    tmp_path: Path,
) -> None:
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

    assert result.payload == {
        "session_id": str(session.session_id),
        "artifact_id": "tool-run:5",
        "database": str(database_path),
        "status": "artifact_access_denied",
        "reason": "artifact_read_requires_full_access_policy",
        "access": {
            "class": "sensitive",
            "required_policy_profile": "full_access",
            "session_policy_profile": "workspace_write",
            "allowed": False,
        },
    }


def test_cli_artifact_read_allows_sensitive_payload_for_full_access(tmp_path: Path) -> None:
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
    assert result.payload["artifact_id"] == "tool-run:5"


def test_cli_artifact_prune_prunes_operator_safe_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.WORKSPACE_WRITE.value)
    _seed_payload_backed_tool_artifact(database_path, session.session_id)

    result = execute(
        [
            "artifact",
            "prune",
            str(session.session_id),
            "tool-run:5",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload["session_id"] == str(session.session_id)
    assert result.payload["artifact_id"] == "tool-run:5"
    assert result.payload["database"] == str(database_path)
    assert result.payload["status"] == "pruned"
    assert result.payload["access"]["class"] == "operator_safe"
    assert result.payload["access_class"] == "operator_safe"
    assert result.payload["required_policy_profile"] == "workspace_write"
    assert result.payload["lifecycle"]["status"] == "pruned"
    assert result.payload["lifecycle"]["retained_until"] is None
    assert result.payload["lifecycle"]["expired"] is False


def test_cli_artifact_prune_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(database_path, session.session_id, PolicyProfile.WORKSPACE_WRITE.value)
    _seed_payload_backed_tool_artifact(database_path, session.session_id)

    first = execute(
        [
            "artifact",
            "prune",
            str(session.session_id),
            "tool-run:5",
            "--database",
            str(database_path),
        ]
    )
    second = execute(
        [
            "artifact",
            "prune",
            str(session.session_id),
            "tool-run:5",
            "--database",
            str(database_path),
        ]
    )

    assert first.payload["status"] == "pruned"
    assert second.payload["status"] == "already_pruned"


def test_cli_artifact_prune_denies_sensitive_payload_for_workspace_write(
    tmp_path: Path,
) -> None:
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
            "prune",
            str(session.session_id),
            "tool-run:5",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": str(session.session_id),
        "artifact_id": "tool-run:5",
        "database": str(database_path),
        "status": "artifact_prune_denied",
        "reason": "artifact_prune_requires_full_access_policy",
    }


def test_cli_artifact_prune_reports_indexed_only_unavailable(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_indexed_artifacts(database_path, session.session_id)

    result = execute(
        [
            "artifact",
            "prune",
            str(session.session_id),
            "model-call:4",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": str(session.session_id),
        "artifact_id": "model-call:4",
        "database": str(database_path),
        "status": "artifact_prune_unavailable",
        "reason": "artifact_is_indexed_only",
    }


def test_cli_artifact_prune_reports_external_reference_unavailable(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    SQLiteToolRunStore(database_path).upsert(
        ToolRunRecord(
            session_id=session.session_id,
            sequence=5,
            tool_name="tests.run",
            status="executed",
            idempotency_key="tool-5",
            output="see external artifact",
            artifact_uri="https://example.com/result.json",
            created_at=_created_at(),
        )
    )

    result = execute(
        [
            "artifact",
            "prune",
            str(session.session_id),
            "tool-run:5",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": str(session.session_id),
        "artifact_id": "tool-run:5",
        "database": str(database_path),
        "status": "artifact_prune_unavailable",
        "reason": "artifact_uses_external_reference",
    }


def _seed_session(database_path: Path) -> Session:
    return SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Artifact session")
    )


def _seed_indexed_artifacts(database_path: Path, session_id: SessionId) -> None:
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


def _seed_payload_backed_tool_artifact(
    database_path: Path,
    session_id: SessionId,
    *,
    mime_type: str = "text/plain",
    payload: bytes = b"pytest passed",
    output: str = "pytest passed",
    file_name: str = "pytest.log",
):
    payload = SQLiteArtifactPayloadStore(database_path).store_payload(
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
            artifact_uri=payload.uri,
            created_at=_created_at(),
        )
    )
    return payload


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
