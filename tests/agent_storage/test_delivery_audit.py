from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteDeliveryAuditStore


def test_sqlite_delivery_audit_store_lists_records_for_session(tmp_path: Path) -> None:
    database_path = tmp_path / "delivery.sqlite"
    store = SQLiteDeliveryAuditStore(database_path)
    session_id = SessionId(UUID("00000000-0000-0000-0000-000000000001"))
    other_session_id = SessionId(UUID("00000000-0000-0000-0000-000000000002"))
    first = _record(session_id, action="session.commit", status="committed")
    second = _record(session_id, action="session.pull_request", status="dry_run")

    store.append(first)
    store.append(_record(other_session_id, action="session.commit", status="committed"))
    store.append(second)

    assert store.list_for_session(session_id) == [first, second]


def test_sqlite_delivery_audit_store_preserves_metadata(tmp_path: Path) -> None:
    store = SQLiteDeliveryAuditStore(tmp_path / "delivery.sqlite")
    session_id = SessionId(UUID("00000000-0000-0000-0000-000000000001"))
    record = DeliveryAuditRecord(
        session_id=session_id,
        action="session.pull_request",
        status="dry_run",
        status_code=200,
        policy_profile="full_access",
        idempotency_key="pr-key-1",
        result_metadata={
            "provider": "local-only",
            "commit_sha": "a" * 40,
            "dry_run": True,
            "url": None,
        },
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
    )

    store.append(record)

    assert store.list_for_session(session_id)[0] == record


def _record(session_id: SessionId, *, action: str, status: str) -> DeliveryAuditRecord:
    return DeliveryAuditRecord(
        session_id=session_id,
        action=action,
        status=status,
        status_code=201 if status == "committed" else 200,
        policy_profile="full_access",
        result_metadata={"commit_sha": "a" * 40},
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
    )
