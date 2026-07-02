from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteDeliveryAuditStore
from zebra_agent_api.delivery_audit import record_delivery_audit
from zebra_agent_api.responses import ApiResponse


def test_delivery_audit_records_created_pull_request_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = "00000000-0000-0000-0000-000000000001"

    record_delivery_audit(
        database_path=database_path,
        session_id=session_id,
        action="session.pull_request",
        response=ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "pull_request": {
                    "provider": "github",
                    "status": "created",
                    "commit_sha": "a" * 40,
                    "dry_run": False,
                    "url": "https://github.example/pulls/1",
                    "credential_source": "broker",
                    "credential_backend": "environment",
                },
            },
        ),
        policy_profile="full_access",
        idempotency_key="pr-key-1",
    )

    records = SQLiteDeliveryAuditStore(database_path).list_for_session(SessionId(UUID(session_id)))

    assert len(records) == 1
    assert records[0].status == "created"
    assert records[0].result_metadata == {
        "provider": "github",
        "status": "created",
        "commit_sha": "a" * 40,
        "dry_run": False,
        "url": "https://github.example/pulls/1",
        "credential_source": "broker",
        "credential_backend": "environment",
        "route": None,
        "proxy_target": None,
        "proxy_transport": None,
    }
    assert "secret-token" not in str(records[0].result_metadata)
