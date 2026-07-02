from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.identifiers import SessionId
from agent_storage import (
    SQLiteDeliveryAuditStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    read_session_delivery_audit_records,
)


def test_read_session_delivery_audit_records_returns_none_for_missing_session(
    tmp_path: Path,
) -> None:
    records = read_session_delivery_audit_records(
        tmp_path / "sessions.sqlite",
        SessionId(UUID("00000000-0000-0000-0000-000000000001")),
    )

    assert records is None


def test_read_session_delivery_audit_records_returns_records_for_existing_session(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, tmp_path)
    created_at = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
    record = DeliveryAuditRecord(
        session_id=session_id,
        action="session.pull_request",
        status="dry_run",
        status_code=200,
        policy_profile="full_access",
        idempotency_key="pr-key-1",
        result_metadata={"provider": "github", "status": "dry_run"},
        created_at=created_at,
    )
    SQLiteDeliveryAuditStore(database_path).append(record)

    records = read_session_delivery_audit_records(database_path, session_id)

    assert records == [record]


def _seed_ready_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Delivery audit read helper",
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
