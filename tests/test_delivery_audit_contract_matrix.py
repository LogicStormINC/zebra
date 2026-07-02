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
from zebra_agent_cli.cli import execute


def test_delivery_audit_contract_matrix_populated_records_match_across_api_and_cli(
    tmp_path: Path,
) -> None:
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
            result_metadata={
                "provider": "github",
                "status": "dry_run",
                "commit_sha": "a" * 40,
                "dry_run": True,
                "url": None,
                "credential_source": None,
                "credential_backend": None,
                "route": "direct",
                "proxy_target": None,
                "proxy_transport": None,
            },
            created_at=created_at,
        )
    )

    api_response = create_app(database_path).get_session_delivery_audit(str(session_id))
    cli_result = execute(
        [
            "delivery-audit",
            str(session_id),
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 200
    assert _normalize_api_delivery_audit(api_response.body) == _normalize_cli_delivery_audit(
        cli_result.payload
    )


def test_delivery_audit_contract_matrix_empty_history_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, tmp_path)

    api_response = create_app(database_path).get_session_delivery_audit(str(session_id))
    cli_result = execute(
        [
            "delivery-audit",
            str(session_id),
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 200
    assert _normalize_api_delivery_audit(api_response.body) == _normalize_cli_delivery_audit(
        cli_result.payload
    )


def test_delivery_audit_contract_matrix_missing_session_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = "00000000-0000-0000-0000-000000000001"

    api_response = create_app(database_path).get_session_delivery_audit(session_id)
    cli_result = execute(
        [
            "delivery-audit",
            session_id,
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 404
    assert _normalize_api_delivery_audit(api_response.body) == _normalize_cli_delivery_audit(
        cli_result.payload
    )


def _normalize_api_delivery_audit(payload: dict[str, object]) -> dict[str, object]:
    if payload.get("status") == "not_found":
        return {
            "session_id": payload["session_id"],
            "status": "not_found",
        }
    return {
        "session_id": payload["session_id"],
        "status": "ok",
        "delivery_audit": payload["delivery_audit"],
    }


def _normalize_cli_delivery_audit(payload: dict[str, object]) -> dict[str, object]:
    if payload.get("status") == "not_found":
        return {
            "session_id": payload["session_id"],
            "status": "not_found",
        }
    return {
        "session_id": payload["session_id"],
        "status": "ok",
        "delivery_audit": payload["delivery_audit"],
    }


def _seed_ready_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Delivery audit contract matrix",
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
