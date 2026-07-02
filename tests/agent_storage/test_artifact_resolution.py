from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.domain.tool_runs import ToolRunRecord
from agent_storage import (
    SQLiteProjectionStore,
    SQLiteToolRunStore,
    resolve_session_artifact,
)


def test_resolve_session_artifact_reports_missing_session(tmp_path: Path) -> None:
    resolution = resolve_session_artifact(
        tmp_path / "sessions.sqlite",
        SessionId(UUID("00000000-0000-0000-0000-000000000001")),
        "tool-run:5",
    )

    assert resolution.session_exists is False
    assert resolution.artifact is None


def test_resolve_session_artifact_reports_missing_artifact_for_existing_session(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Artifact resolution")
    )

    resolution = resolve_session_artifact(
        database_path,
        session.session_id,
        "tool-run:5",
    )

    assert resolution.session_exists is True
    assert resolution.artifact is None


def test_resolve_session_artifact_returns_matching_artifact(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Artifact resolution")
    )
    SQLiteToolRunStore(database_path).upsert(
        ToolRunRecord(
            session_id=session.session_id,
            sequence=5,
            tool_name="tests.run",
            status="executed",
            idempotency_key="tool-5",
            output="artifact output",
            artifact_uri="file:///tmp/tool-run-5.txt",
            created_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )
    )

    resolution = resolve_session_artifact(
        database_path,
        session.session_id,
        "tool-run:5",
    )

    assert resolution.session_exists is True
    assert resolution.artifact is not None
    assert resolution.artifact.artifact_id == "tool-run:5"
