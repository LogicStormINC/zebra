from datetime import UTC, datetime
from uuid import uuid4

from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.identifiers import SessionId
from agent_storage import (
    serialize_delivery_audit_record,
    serialize_session_delivery_audit_projection,
)


def test_serialize_delivery_audit_record_builds_shared_payload() -> None:
    created_at = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
    record = DeliveryAuditRecord(
        session_id=SessionId(uuid4()),
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

    assert serialize_delivery_audit_record(record) == {
        "action": "session.pull_request",
        "status": "dry_run",
        "status_code": 200,
        "policy_profile": "full_access",
        "idempotency_key": "pr-key-1",
        "result_metadata": {
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
        "created_at": created_at.isoformat(),
    }


def test_serialize_session_delivery_audit_projection_builds_shared_envelope() -> None:
    created_at = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
    session_id = str(uuid4())
    record = DeliveryAuditRecord(
        session_id=SessionId(uuid4()),
        action="session.commit",
        status="created",
        status_code=201,
        policy_profile="workspace_write",
        idempotency_key=None,
        result_metadata={"commit_sha": "b" * 40},
        created_at=created_at,
    )

    assert serialize_session_delivery_audit_projection(session_id, [record]) == {
        "session_id": session_id,
        "delivery_audit": [
            {
                "action": "session.commit",
                "status": "created",
                "status_code": 201,
                "policy_profile": "workspace_write",
                "idempotency_key": None,
                "result_metadata": {"commit_sha": "b" * 40},
                "created_at": created_at.isoformat(),
            }
        ],
    }
