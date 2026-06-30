from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.identifiers import new_session_id
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.tool_runs import ToolRunRecord
from agent_storage import SQLiteArtifactStore, SQLiteModelCallStore, SQLiteToolRunStore


def test_sqlite_artifact_store_lists_model_and_tool_artifacts(tmp_path: Path) -> None:
    database_path = tmp_path / "artifacts.db"
    session_id = new_session_id()
    created_at = datetime(2026, 6, 23, 14, 0, tzinfo=UTC)
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
            created_at=created_at,
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
            artifact_uri="file:///tmp/pytest.log",
            created_at=created_at,
        )
    )

    artifacts = SQLiteArtifactStore(database_path).list_for_session(session_id)

    assert [artifact.artifact_id for artifact in artifacts] == [
        "model-call:4",
        "tool-run:5",
    ]
    assert artifacts[0].source == "model_call"
    assert artifacts[0].kind == "assistant_message"
    assert artifacts[0].preview == "Summarized the repository."
    assert artifacts[0].preview_state == {"redacted": False, "truncated": False}
    assert artifacts[0].metadata["total_tokens"] == 30
    assert artifacts[1].source == "tool_run"
    assert artifacts[1].kind == "tool_output"
    assert artifacts[1].uri == "file:///tmp/pytest.log"
    assert artifacts[1].preview_state == {"redacted": False, "truncated": False}
    assert artifacts[1].metadata["status"] == "executed"


def test_sqlite_artifact_store_redacts_and_truncates_sensitive_preview(tmp_path: Path) -> None:
    database_path = tmp_path / "artifacts.db"
    session_id = new_session_id()
    SQLiteToolRunStore(database_path).upsert(
        ToolRunRecord(
            session_id=session_id,
            sequence=5,
            tool_name="tests.run",
            status="executed",
            idempotency_key="tool-5",
            output="token=super-secret-value " + ("x" * 200),
            artifact_uri=None,
            created_at=datetime(2026, 6, 23, 14, 0, tzinfo=UTC),
        )
    )

    artifacts = SQLiteArtifactStore(database_path).list_for_session(session_id)

    assert artifacts[0].preview.endswith("...")
    assert "[REDACTED]" in artifacts[0].preview
    assert artifacts[0].preview_state == {"redacted": True, "truncated": True}


def test_sqlite_artifact_store_returns_empty_list(tmp_path: Path) -> None:
    artifacts = SQLiteArtifactStore(tmp_path / "artifacts.db").list_for_session(new_session_id())

    assert artifacts == []
