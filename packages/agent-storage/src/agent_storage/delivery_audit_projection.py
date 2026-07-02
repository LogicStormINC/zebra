from __future__ import annotations

from collections.abc import Sequence

from agent_core.domain.delivery_audit import DeliveryAuditRecord


def serialize_delivery_audit_record(record: DeliveryAuditRecord) -> dict[str, object]:
    return {
        "action": record.action,
        "status": record.status,
        "status_code": record.status_code,
        "policy_profile": record.policy_profile,
        "idempotency_key": record.idempotency_key,
        "result_metadata": record.result_metadata,
        "created_at": record.created_at.isoformat(),
    }


def serialize_session_delivery_audit_projection(
    session_id: str,
    records: Sequence[DeliveryAuditRecord],
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "delivery_audit": [serialize_delivery_audit_record(record) for record in records],
    }
