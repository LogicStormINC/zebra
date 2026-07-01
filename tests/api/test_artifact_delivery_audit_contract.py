from datetime import UTC, datetime
from pathlib import Path
from typing import cast

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


def test_delivery_audit_preserves_artifact_read_denied_metadata_contract(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(
        database_path,
        session.session_id,
        PolicyProfile.WORKSPACE_WRITE.value,
    )
    _seed_payload_backed_tool_artifact(
        database_path,
        session.session_id,
        mime_type="application/json",
        payload=b'{"token":"secret"}',
        output='{"token":"secret"}',
        file_name="result.json",
    )
    api = create_app(database_path)

    response = api.get_session_artifact_content(str(session.session_id), "tool-run:5")
    audit_response = api.get_session_delivery_audit(str(session.session_id))

    assert response.status_code == 409
    assert audit_response.status_code == 200
    delivery_audit = cast(list[dict[str, object]], audit_response.body["delivery_audit"])
    record = delivery_audit[0]
    assert record["action"] == "session.artifact.content"
    assert record["status"] == "artifact_access_denied"
    assert record["status_code"] == 409
    assert record["policy_profile"] == "workspace_write"
    assert record["idempotency_key"] is None
    assert record["result_metadata"] == {
        "reason": "artifact_read_requires_full_access_policy",
        "artifact_id": "tool-run:5",
        "access_class": "sensitive",
        "required_policy_profile": "full_access",
        "session_policy_profile": "workspace_write",
        "result_status": "artifact_access_denied",
        "retrieval_status": "access_denied",
    }
    datetime.fromisoformat(cast(str, record["created_at"]))


def test_delivery_audit_preserves_artifact_prune_success_metadata_contract(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_workspace_policy(
        database_path,
        session.session_id,
        PolicyProfile.WORKSPACE_WRITE.value,
    )
    payload = _seed_payload_backed_tool_artifact(database_path, session.session_id)
    api = create_app(database_path)

    response = api.prune_session_artifact(str(session.session_id), "tool-run:5")
    audit_response = api.get_session_delivery_audit(str(session.session_id))

    assert response.status_code == 200
    assert audit_response.status_code == 200
    delivery_audit = cast(list[dict[str, object]], audit_response.body["delivery_audit"])
    record = delivery_audit[0]
    assert record["action"] == "session.artifact.prune"
    assert record["status"] == "pruned"
    assert record["status_code"] == 200
    assert record["policy_profile"] == "workspace_write"
    assert record["idempotency_key"] is None
    assert record["result_metadata"] == {
        "reason": None,
        "artifact_id": "tool-run:5",
        "access_class": "operator_safe",
        "required_policy_profile": "workspace_write",
        "session_policy_profile": "workspace_write",
        "result_status": "pruned",
        "payload_artifact_id": str(payload.artifact_id),
        "lifecycle_status": "pruned",
    }
    datetime.fromisoformat(cast(str, record["created_at"]))


def _seed_session(database_path: Path) -> Session:
    return SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Artifact delivery audit contract")
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
    stored_payload = SQLiteArtifactPayloadStore(database_path).store_payload(
        ArtifactPayloadWrite(
            session_id=session_id,
            kind="tool_output",
            mime_type=mime_type,
            payload=payload,
            file_name=file_name,
            retained_until=None,
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
            artifact_uri=stored_payload.uri,
            created_at=_created_at(),
        )
    )
    return stored_payload


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
    return datetime(2026, 6, 23, 14, 0, tzinfo=UTC)
