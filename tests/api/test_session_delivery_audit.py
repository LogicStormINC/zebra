from datetime import UTC, datetime
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.identifiers import SessionId
from agent_storage import (
    SQLiteDeliveryAuditStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
)
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_api_delivery_audit_returns_empty_list(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, tmp_path)

    response = create_app(database_path).get_session_delivery_audit(str(session_id))

    assert response.status_code == 200
    assert response.body == {
        "session_id": str(session_id),
        "delivery_audit": [],
    }


def test_api_delivery_audit_returns_not_found(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").get_session_delivery_audit(
        "00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.body == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def test_api_delivery_audit_lists_records(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, tmp_path)
    created_at = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
    SQLiteDeliveryAuditStore(database_path).append(
        DeliveryAuditRecord(
            session_id=session_id,
            action="session.pull_request",
            status="dry_run",
            status_code=200,
            policy_profile="full_access",
            idempotency_key="pr-key-1",
            result_metadata={"provider": "github", "commit_sha": "a" * 40},
            created_at=created_at,
        )
    )

    response = create_app(database_path).get_session_delivery_audit(str(session_id))

    assert response.status_code == 200
    assert response.body == {
        "session_id": str(session_id),
        "delivery_audit": [
            {
                "action": "session.pull_request",
                "status": "dry_run",
                "status_code": 200,
                "policy_profile": "full_access",
                "idempotency_key": "pr-key-1",
                "result_metadata": {"provider": "github", "commit_sha": "a" * 40},
                "created_at": created_at.isoformat(),
            }
        ],
    }


def test_route_adapter_handles_delivery_audit(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, tmp_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="GET",
            path=f"/sessions/{session_id}/delivery-audit",
        )
    )

    assert response.status_code == 200
    assert response.body == {
        "session_id": str(session_id),
        "delivery_audit": [],
    }


def _seed_ready_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Delivery audit session",
            user_input="Inspect delivery audit.",
            workspace_root=workspace_root.resolve(),
            policy_profile="full_access",
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id
