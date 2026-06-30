import base64
from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.identifiers import SessionId
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.sessions import Session
from agent_core.domain.tool_runs import ToolRunRecord
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteModelCallStore,
    SQLiteProjectionStore,
    SQLiteToolRunStore,
)
from zebra_agent_cli.cli import execute


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
    assert result.payload["artifact"]["retrieval"] == {
        "status": "payload_available",
        "retrievable": True,
        "uri": payload.uri,
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
        "encoding": "base64",
        "content_base64": base64.b64encode(b"pytest passed").decode("ascii"),
        "size_bytes": 13,
    }


def test_cli_artifact_read_reports_missing_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    payload = _seed_payload_backed_tool_artifact(database_path, session.session_id)
    Path(payload.uri.removeprefix("file://")).unlink()

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


def _seed_payload_backed_tool_artifact(database_path: Path, session_id: SessionId):
    payload = SQLiteArtifactPayloadStore(database_path).store_payload(
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
            artifact_uri=payload.uri,
            created_at=_created_at(),
        )
    )
    return payload


def _created_at() -> datetime:
    return datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
