from datetime import UTC, datetime
from pathlib import Path

from agent_storage import (
    SQLiteDeliveryAuditStore,
)
from session_artifact_support import (
    _created_at,
    _seed_artifacts,
    _seed_payload_backed_tool_artifact,
    _seed_session,
)
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_api_get_session_artifacts_returns_indexed_artifacts(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_artifacts(database_path, session.session_id)

    response = create_app(database_path).get_session_artifacts(str(session.session_id))

    assert response.status_code == 200
    assert response.body["session_id"] == str(session.session_id)
    assert response.body["artifacts"] == [
        {
            "artifact_id": "model-call:4",
            "sequence": 4,
            "source": "model_call",
            "kind": "assistant_message",
            "label": "deepseek-v4-flash",
            "uri": None,
            "preview": "Summarized the repository.",
            "preview_state": {
                "redacted": False,
                "truncated": False,
            },
            "metadata": {
                "provider": "deepseek",
                "model_name": "deepseek-v4-flash",
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
                "latency_ms": 250,
                "cache_hit": False,
                "cost_usd": 0.001,
                "tool_call_count": 1,
                "created_at": _created_at().isoformat(),
            },
            "retrieval": {
                "status": "indexed_only",
                "retrievable": False,
                "uri": None,
            },
            "lifecycle": None,
            "access": {
                "class": "operator_safe",
                "required_policy_profile": "workspace_write",
                "session_policy_profile": "workspace_write",
                "allowed": True,
            },
        },
        {
            "artifact_id": "tool-run:5",
            "sequence": 5,
            "source": "tool_run",
            "kind": "tool_output",
            "label": "tests.run",
            "uri": "file:///tmp/pytest.log",
            "preview": "pytest passed",
            "preview_state": {
                "redacted": False,
                "truncated": False,
            },
            "metadata": {
                "tool_name": "tests.run",
                "status": "executed",
                "idempotency_key": "tool-5",
                "created_at": _created_at().isoformat(),
            },
            "retrieval": {
                "status": "payload_missing",
                "retrievable": False,
                "uri": "file:///tmp/pytest.log",
            },
            "lifecycle": None,
            "access": {
                "class": "sensitive",
                "required_policy_profile": "full_access",
                "session_policy_profile": "workspace_write",
                "allowed": False,
            },
        },
    ]

def test_api_get_session_artifacts_returns_empty_list(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)

    response = create_app(database_path).get_session_artifacts(str(session.session_id))

    assert response.status_code == 200
    assert response.body == {
        "session_id": str(session.session_id),
        "artifacts": [],
    }

def test_api_get_session_artifacts_returns_not_found(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").get_session_artifacts(
        "00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.body == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }

def test_route_adapter_handles_session_artifacts(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_artifacts(database_path, session.session_id)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(method="GET", path=f"/sessions/{session.session_id}/artifacts")
    )

    assert response.status_code == 200
    assert response.body["session_id"] == str(session.session_id)
    assert len(response.body["artifacts"]) == 2

def test_api_get_session_artifact_detail_distinguishes_indexed_and_payload_backed(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    payload = _seed_payload_backed_tool_artifact(
        database_path,
        session.session_id,
        retained_until=datetime(2099, 6, 30, 14, 0, tzinfo=UTC),
    )

    response = create_app(database_path).get_session_artifact_detail(
        str(session.session_id),
        "tool-run:5",
    )

    assert response.status_code == 200
    assert response.body["status"] == "ok"
    assert response.body["artifact"]["uri"] == payload.uri
    assert response.body["artifact"]["preview_state"] == {
        "redacted": False,
        "truncated": False,
    }
    assert response.body["artifact"]["retrieval"] == {
        "status": "payload_available",
        "retrievable": True,
        "uri": payload.uri,
    }
    assert response.body["artifact"]["lifecycle"] == {
        "status": "active",
        "retained_until": datetime(2099, 6, 30, 14, 0, tzinfo=UTC).isoformat(),
        "pruned_at": None,
        "expired": False,
    }
    audit = SQLiteDeliveryAuditStore(database_path).list_for_session(session.session_id)
    assert audit[-1].action == "session.artifact.detail"
    assert audit[-1].result_metadata["artifact_id"] == "tool-run:5"
    assert audit[-1].result_metadata["retrieval_status"] == "payload_available"

def test_api_get_session_artifact_detail_reports_indexed_only(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_artifacts(database_path, session.session_id)

    response = create_app(database_path).get_session_artifact_detail(
        str(session.session_id),
        "model-call:4",
    )

    assert response.status_code == 200
    assert response.body["status"] == "ok"
    assert response.body["artifact"]["retrieval"] == {
        "status": "indexed_only",
        "retrievable": False,
        "uri": None,
    }
    assert response.body["artifact"]["lifecycle"] is None

def test_api_get_session_artifacts_includes_lifecycle_for_payload_backed_artifacts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_session(database_path)
    _seed_payload_backed_tool_artifact(
        database_path,
        session.session_id,
        retained_until=datetime(2099, 6, 30, 13, 0, tzinfo=UTC),
    )

    response = create_app(database_path).get_session_artifacts(str(session.session_id))

    assert response.status_code == 200
    tool_artifact = response.body["artifacts"][0]
    assert tool_artifact["lifecycle"] == {
        "status": "active",
        "retained_until": datetime(2099, 6, 30, 13, 0, tzinfo=UTC).isoformat(),
        "pruned_at": None,
        "expired": False,
    }
