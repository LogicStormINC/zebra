"""Exact durable-frame rewind for signed stream wire chunks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.ports.stream_source_head import StreamObservationReadPort
from agent_integrations.ag_ui import AgUiCursor

from zebra_agent_api.stream_v2_reader import V2StreamContext

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi


def _source_query(
    api: ZebraAgentApi,
    context: V2StreamContext,
    query: Mapping[str, str],
    *,
    initial_metadata: StreamObservationReadPort | None = None,
) -> dict[str, str]:
    result = {
        key: value
        for key, value in query.items()
        if key not in {"cursor", "after", "last_event_id", "after_sequence"}
    }
    if context.full_recovery or context.cursor.durable is None:
        return result
    original = context.cursor.durable
    if context.kind != "agui":
        coordinate = int(original)
        result["after_sequence"] = str(coordinate - int(context.cursor.chunk_index is not None))
        return result
    cursor = AgUiCursor.decode(original)
    if context.cursor.chunk_index is not None:
        from agent_integrations.ag_ui import AgUiRunIdentity
        from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver

        assert context.binding.authority.allowed_session_ids is not None
        identity = AgUiRunIdentity(
            session_id=SessionId(UUID(context.binding.authority.allowed_session_ids[0])),
            thread_id=str(context.binding.task_id),
            run_id=context.binding.run_id,
        )
        observer = AgUiCheckpointObserver(
            api.stores.tasks,
            namespace=context.binding.namespace,
            initial_metadata=initial_metadata,
            profile=getattr(context, "profile", None),
        )
        observer.validate_cursor(
            observer.snapshot(context.binding.task_id, identity), identity, cursor
        )
        if cursor.frame_index is not None and cursor.frame_index > 0:
            cursor = cursor.model_copy(update={"frame_index": cursor.frame_index - 1})
        else:
            previous = (
                initial_metadata if initial_metadata is not None else api.stores.tasks
            ).read_event_header(context.binding.task_id, cursor.sequence - 1)
            if previous is None:
                return result
            cursor = AgUiCursor(
                thread_id=cursor.thread_id,
                run_id=cursor.run_id,
                sequence=previous.task_sequence,
                event_id=str(previous.event_id),
                version=cursor.version,
                profile_scope=cursor.profile_scope,
            )
    result["cursor"] = cursor.encode()
    return result
