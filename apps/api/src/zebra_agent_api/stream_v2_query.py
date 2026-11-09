"""Exact durable-frame rewind for signed stream wire chunks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID

from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.stream_source_head import StreamObservationReadPort
from agent_integrations.ag_ui import AgUiCursor
from agent_storage.postgres.stream_proof_batch import StreamProofSnapshot
from fastapi import Request
from fastapi.responses import JSONResponse

from zebra_agent_api.ag_ui_observation_binding import stream_negotiation_problem
from zebra_agent_api.request_cursor import after_sequence
from zebra_agent_api.responses import ApiResponse
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


def source_query(
    api: ZebraAgentApi,
    context: V2StreamContext,
    query: Mapping[str, str],
    *,
    initial_metadata: StreamObservationReadPort | None = None,
) -> dict[str, str] | ApiResponse:
    try:
        return _source_query(api, context, query, initial_metadata=initial_metadata)
    except ValueError:
        return stream_negotiation_problem(400, "invalid_cursor")

def legacy_cursor_position(
    request: Request, proof: StreamProofSnapshot,
) -> tuple[UUID, int, SessionId | None] | JSONResponse:
    after, error = after_sequence(request)
    if error is not None:
        return error
    _, kind, raw_id, _ = request.url.path.split("/")
    resource = UUID(raw_id)  # The authorized raw preflight already checked the path.
    segment = None
    if kind == "tasks":
        header = proof.read_task_header(TaskId(resource), require_source_coverage=True)
        if header is None:
            return JSONResponse(status_code=404, content={"status": "not_found"})
        highwater, segment = header.current_sequence, header.active_segment_id
    else:
        highwater = proof.read_session_highwater(SessionId(resource))
    if after > highwater:
        label = "Task" if kind == "tasks" else "Session"
        return JSONResponse(
            status_code=400,
            content={
                "status": "invalid_request",
                "reason": f"after_sequence exceeds {label} highwater",
            },
        )
    return resource, after, segment
