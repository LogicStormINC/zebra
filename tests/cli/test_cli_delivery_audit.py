from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.sessions import Session
from agent_storage import SQLiteDeliveryAuditStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_delivery_audit_lists_records(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Delivery audit session")
    )
    created_at = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
    SQLiteDeliveryAuditStore(database_path).append(
        DeliveryAuditRecord(
            session_id=session.session_id,
            action="session.artifact.content",
            status="artifact_access_denied",
            status_code=409,
            policy_profile="workspace_write",
            idempotency_key=None,
            result_metadata={
                "artifact_id": "tool-run:5",
                "access_class": "sensitive",
                "result_status": "artifact_access_denied",
                "retrieval_status": "access_denied",
                "reason": "artifact_read_requires_full_access_policy",
            },
            created_at=created_at,
        )
    )

    result = execute(
        [
            "delivery-audit",
            str(session.session_id),
            "--database",
            str(database_path),
        ]
    )

    assert result.command == "delivery-audit"
    assert result.payload == {
        "session_id": str(session.session_id),
        "database": str(database_path),
        "status": "ok",
        "delivery_audit": [
            {
                "action": "session.artifact.content",
                "status": "artifact_access_denied",
                "status_code": 409,
                "policy_profile": "workspace_write",
                "idempotency_key": None,
                "result_metadata": {
                    "artifact_id": "tool-run:5",
                    "access_class": "sensitive",
                    "result_status": "artifact_access_denied",
                    "retrieval_status": "access_denied",
                    "reason": "artifact_read_requires_full_access_policy",
                },
                "created_at": created_at.isoformat(),
            }
        ],
    }


def test_cli_delivery_audit_returns_empty_list(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="No audit yet")
    )

    result = execute(
        [
            "delivery-audit",
            str(session.session_id),
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": str(session.session_id),
        "database": str(database_path),
        "status": "ok",
        "delivery_audit": [],
    }


def test_cli_delivery_audit_reports_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "delivery-audit",
            "00000000-0000-0000-0000-000000000001",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "database": str(database_path),
        "status": "not_found",
    }
