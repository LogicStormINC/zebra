"""Namespace-scoped original receipt observation, without resume or status mutation."""

from typing import Any
from uuid import UUID

from agent_core.domain.client_effects import ClientEffectReceipt, ClientEffectStatus
from agent_core.domain.identifiers import ClientEffectId

from agent_storage.postgres.database import PostgresDatabase


def read_receipt(
    database: PostgresDatabase, namespace: str, effect_id: ClientEffectId
) -> ClientEffectReceipt | None:
    with database.connect_task_io() as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        row = connection.execute(
            "SELECT * FROM client_effect_receipts "
            "WHERE deployment_namespace = %s AND effect_id = %s",
            (namespace, effect_id),
        ).fetchone()
    return None if row is None else receipt_from_row(row)


def receipt_from_row(row: Any) -> ClientEffectReceipt:
    return ClientEffectReceipt(
        receipt_id=UUID(str(row["receipt_id"])),
        effect_id=ClientEffectId(UUID(str(row["effect_id"]))),
        idempotency_key=row["idempotency_key"],
        request_digest=row["request_digest"],
        status=ClientEffectStatus(row["status"]),
        result=dict(row["result_json"]),
        received_at=row["received_at"],
    )
