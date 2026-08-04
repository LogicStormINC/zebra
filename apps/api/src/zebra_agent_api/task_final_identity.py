from __future__ import annotations

from pathlib import Path

from agent_core.application.public_conversation import project_public_conversation
from agent_storage import SQLiteAgentTaskStore


def final_message_identity(
    database_path: Path, task_id: str
) -> dict[str, object] | None:
    """Stable identity of the latest completed final message of a Task.

    This is the same identity the public conversation projection exposes
    (``item_id`` / ``cursor`` for ``final_response`` items), so a consumer can
    bind a persisted artifact to the exact message that produced it without
    comparing content or assuming array order.
    """
    store = SQLiteAgentTaskStore(database_path)
    try:
        events = store.read_events(task_id, -1)
    except ValueError:
        # A task whose projection is not (yet) complete has no stable final
        # identity; the caller treats the identity as absent.
        return None
    projection = project_public_conversation(
        task_id, events, after_sequence=-1
    )
    final = next(
        (
            item
            for item in reversed(projection.items)
            if item.role == "final_response" and item.state == "completed"
        ),
        None,
    )
    if final is None:
        return None
    return {"message_id": final.item_id, "cursor": final.cursor}
