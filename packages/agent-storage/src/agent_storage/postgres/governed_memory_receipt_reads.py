"""Validated read-only lookup for governed Memory operation receipts."""

from typing import Any

from agent_core.domain.governed_memories import GovernedMemoryConflictError
from agent_core.domain.governed_memory_operations import GovernedMemoryOperationKind
from agent_core.domain.governed_memory_receipts import (
    GovernedMemoryCommitResult,
    GovernedMemoryOperationReceipt,
)
from agent_core.domain.identifiers import SessionId


def read_operation_receipt(
    connection: Any,
    namespace: str,
    operation_id: str,
    *,
    kind: GovernedMemoryOperationKind,
    session_id: SessionId,
    request_digest: str | None = None,
    lock: bool = False,
) -> GovernedMemoryCommitResult | None:
    """Return a canonical receipt only when its stored Event anchor still matches."""
    if not operation_id or operation_id != operation_id.strip():
        raise GovernedMemoryConflictError("Memory operation ID is invalid")
    row = connection.execute(
        """
        SELECT operation_kind, request_digest, session_id,
               anchor_event_start, anchor_event_end,
               anchor_start_event_id, anchor_end_event_id,
               result_schema, result_json, result_digest, committed_at
        FROM governed_memory_operations
        WHERE deployment_namespace = %s AND operation_id = %s
        """ + (" FOR UPDATE" if lock else ""),
        (namespace, operation_id),
    ).fetchone()
    if row is None:
        return None
    if (
        row["operation_kind"] != kind.value
        or row["session_id"] != session_id
        or (request_digest is not None and row["request_digest"] != request_digest)
    ):
        raise GovernedMemoryConflictError("Memory operation identity was reused")
    receipt = GovernedMemoryOperationReceipt.model_validate(row["result_json"])
    if (
        receipt.operation_id != operation_id
        or receipt.operation_kind is not kind
        or receipt.request_digest != row["request_digest"]
        or receipt.result_schema != row["result_schema"]
        or receipt.result_digest != row["result_digest"]
        or receipt.anchor_event_start != row["anchor_event_start"]
        or receipt.anchor_event_end != row["anchor_event_end"]
        or receipt.event_ids[0] != row["anchor_start_event_id"]
        or receipt.event_ids[-1] != row["anchor_end_event_id"]
        or receipt.committed_at != row["committed_at"]
    ):
        raise GovernedMemoryConflictError("stored Memory operation receipt is inconsistent")
    anchors = connection.execute(
        """
        SELECT event_id, sequence FROM session_events
        WHERE deployment_namespace = %s AND session_id = %s
          AND sequence BETWEEN %s AND %s
        ORDER BY sequence
        """,
        (
            namespace,
            session_id,
            receipt.anchor_event_start,
            receipt.anchor_event_end,
        ),
    ).fetchall()
    if (
        tuple(row["event_id"] for row in anchors) != receipt.event_ids
        or tuple(row["sequence"] for row in anchors) != receipt.event_sequences
    ):
        raise GovernedMemoryConflictError("stored Memory operation Event anchor is inconsistent")
    return GovernedMemoryCommitResult(receipt=receipt, replayed=True)
