"""Namespace-qualified existing unique-index lookup with bounded selected bytes."""

from typing import Any
from uuid import UUID

from agent_core.ports.client_command_receipts import ClientCommandReceipt

QUERY = """
SELECT left(payload->>'command_id',37) AS command_id
FROM session_events
WHERE deployment_namespace = %s AND session_id = %s AND idempotency_key = %s
AND event_type = 'session_command_accepted'
AND jsonb_typeof(payload#>'{payload,client,client_state_admission_contract_version}') = 'number'
AND payload#>>'{payload,client,client_state_admission_contract_version}' = '1'
AND payload#>>'{payload,thread_id}' = %s
AND payload#>>'{payload,run_id}' = %s
AND payload#>>'{payload,client,client_session_id}' = %s
LIMIT 1
"""


def read_receipt(connection: Any, params: tuple[str, ...]) -> ClientCommandReceipt | None:
    row = connection.execute(QUERY, params).fetchone()
    return None if row is None else ClientCommandReceipt(UUID(row["command_id"]))
