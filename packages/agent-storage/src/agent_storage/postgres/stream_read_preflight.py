"""Shared canonical source qualification before public stream body hydration."""

from typing import Any

from agent_core.domain.identifiers import TaskId

from agent_storage.postgres.stream_source_head import qualify_source, source_row


def require_stream_source(connection: Any, namespace: str, task_id: TaskId, task: Any) -> bool:
    row = source_row(connection, namespace, task_id)
    if row is None:
        from agent_core.ports.task_projection_checkpoints import CheckpointNotReady

        raise CheckpointNotReady("canonical stream source is unavailable")
    if any(
        row[key] != task[key]
        for key in (
            "active_segment_id",
            "next_event_sequence",
            "active_segment_sequence",
        )
    ):
        from agent_core.ports.task_projection_checkpoints import CheckpointNotReady

        raise CheckpointNotReady("stream source changed while qualifying its header")
    return qualify_source(row)
