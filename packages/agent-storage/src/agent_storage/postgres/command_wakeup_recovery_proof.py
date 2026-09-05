"""Generation approval checks shared by relay and execution handoff."""

from typing import Any

from agent_core.contracts.broker_envelope import ZebraCommandEnvelope


def recovery_approval(connection: Any, envelope: ZebraCommandEnvelope) -> dict[str, Any] | None:
    if envelope.wake_generation == 0:
        return None
    row: dict[str, Any] | None = connection.execute(
        """SELECT * FROM command_recovery_attempts WHERE deployment_namespace = %s
           AND accepted_event_id = %s AND wake_generation = %s""",
        (envelope.deployment_namespace, envelope.accepted_event_id, envelope.wake_generation),
    ).fetchone()
    if (row is None or str(row["message_id"]) != envelope.message_id
            or str(row["previous_message_id"]) != envelope.causation_id):
        raise ValueError("missing or mismatched command recovery approval")
    return row
