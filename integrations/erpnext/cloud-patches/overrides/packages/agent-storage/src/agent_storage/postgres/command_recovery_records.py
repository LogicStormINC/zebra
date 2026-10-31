from datetime import datetime
from typing import Any
from uuid import UUID


def _receipt_snapshot(receipt: dict[str, Any]) -> dict[str, Any]:
    # Explicit allowlist: never let future receipt columns leak into audit JSON.
    fields = (
        "scope_key",
        "command_id",
        "accepted_event_id",
        "session_id",
        "status",
        "control_plane_epoch",
        "fencing_token",
        "owner_instance_id",
        "created_at",
        "execution_floor_sequence",
        "started_event_id",
        "handled_event_id",
        "turn_id",
        "wake_generation",
    )
    return {
        field: (value if value is None or isinstance(value, str | int) else str(value))
        for field in fields
        for value in (receipt[field],)
    }


def _defer(connection: Any, namespace: str, event_id: UUID, due: datetime) -> None:
    connection.execute(
        """UPDATE session_command_pending SET recovery_due_at = %s
           WHERE deployment_namespace = %s AND accepted_event_id = %s""",
        (due, namespace, event_id),
    )


def _stop(connection: Any, namespace: str, event_id: UUID, code: str) -> None:
    connection.execute(
        """UPDATE session_command_pending SET status = 'dead', recovery_code = %s
           WHERE deployment_namespace = %s AND accepted_event_id = %s""",
        (code, namespace, event_id),
    )
