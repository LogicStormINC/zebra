from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, Mock
from uuid import UUID

from agent_core.domain.identifiers import new_session_id
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.tool_runs import ToolRunRecord
from agent_storage import PostgresSessionArtifactReadStore, compose_session_artifacts

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def test_shared_composition_orders_and_sanitizes_model_and_tool_projections() -> None:
    session_id = new_session_id()
    artifacts = compose_session_artifacts(
        [
            ModelCallRecord(
                session_id=session_id,
                sequence=4,
                provider="deepseek",
                model_name=None,
                assistant_message="token=secret-value " + "x" * 170,
                tool_call_count=1,
                created_at=NOW,
            )
        ],
        [
            ToolRunRecord(
                session_id=session_id,
                sequence=2,
                tool_name="tests.run",
                status="executed",
                output="ghp_1234567890abcdef",
                artifact_uri="artifact://00000000-0000-0000-0000-000000000001",
                created_at=NOW,
            )
        ],
    )

    assert [artifact.artifact_id for artifact in artifacts] == ["tool-run:2", "model-call:4"]
    assert artifacts[0].preview == "[REDACTED]"
    assert artifacts[0].preview_state == {"redacted": True, "truncated": False}
    assert artifacts[1].label == "deepseek"
    assert artifacts[1].preview.startswith("token=[REDACTED]")
    assert artifacts[1].preview.endswith("...")
    assert artifacts[1].preview_state == {"redacted": True, "truncated": True}


def test_postgres_artifact_reads_are_namespace_scoped_and_use_shared_composition() -> None:
    session_id = new_session_id()
    connection = Mock()
    connection.execute.return_value = _result(
        {
            "source": "model_call",
            "event_id": UUID("00000000-0000-0000-0000-000000000001"),
            "record": {
                "session_id": session_id,
                "sequence": 1,
                "provider": "openai",
                "model_name": "gpt-test",
                "input_tokens": 3,
                "estimated_input_tokens": None,
                "input_token_limit": None,
                "input_token_estimate_error": None,
                "output_tokens": 5,
                "total_tokens": 8,
                "latency_ms": 12,
                "cache_hit": False,
                "cost_usd": 0.01,
                "assistant_message": "answer",
                "tool_call_count": 1,
                "created_at": NOW,
            },
        },
        {
            "source": "tool_run",
            "event_id": UUID("00000000-0000-0000-0000-000000000002"),
            "record": {
                "session_id": session_id,
                "sequence": 2,
                "tool_name": "files.read",
                "status": "executed",
                "idempotency_key": "tool-2",
                "output": "contents",
                "artifact_uri": None,
                "created_at": NOW,
            },
        },
    )
    database = MagicMock(deployment_namespace="tenant-a")
    database.connect.return_value.__enter__.return_value = connection
    store = PostgresSessionArtifactReadStore(
        "postgresql://unused",
        deployment_namespace="tenant-a",
    )
    store._database = database  # type: ignore[assignment]

    artifacts = store.list_for_session(session_id)

    assert [artifact.artifact_id for artifact in artifacts] == ["model-call:1", "tool-run:2"]
    assert [str(artifact.source_event_id) for artifact in artifacts] == [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]
    connection.execute.assert_called_once()
    query, parameters = connection.execute.call_args.args
    assert query.count("deployment_namespace = %s AND session_id = %s") == 2
    assert parameters == ("tenant-a", session_id, "tenant-a", session_id)


def _result(*rows: dict[str, Any]) -> Mock:
    result = Mock()
    result.fetchall.return_value = list(rows)
    return result
