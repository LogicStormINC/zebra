"""SQLite indexed header projection; no event hydration or history scan."""

from typing import Any
from uuid import UUID

from agent_core.ports.client_command_receipts import ClientCommandReceipt

QUERY = """
SELECT substr(json_extract(payload,'$.command_id'),1,37) AS command_id
FROM session_events
WHERE session_id = ? AND idempotency_key = ?
AND event_type = 'session_command_accepted'
AND json_type(payload,'$.payload.client.client_state_admission_contract_version') = 'integer'
AND json_extract(payload,'$.payload.client.client_state_admission_contract_version') = 1
AND json_extract(payload,'$.payload.thread_id') = ?
AND json_extract(payload,'$.payload.run_id') = ?
AND json_extract(payload,'$.payload.client.client_session_id') = ?
LIMIT 1
"""


def read_receipt(connection: Any, params: tuple[str, ...]) -> ClientCommandReceipt | None:
    row = connection.execute(QUERY, params).fetchone()
    return None if row is None else ClientCommandReceipt(UUID(row["command_id"]))
