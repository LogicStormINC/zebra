"""Read-only stream negotiation after the existing signed Host/tenant boundary."""

from collections.abc import AsyncGenerator, Mapping
from pathlib import Path
from typing import cast
from uuid import UUID

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_integrations.ag_ui import AgUiCursor
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from zebra_agent_api.ag_ui_stream import AgUiStreamContext, prepare_agui_stream, tail_agui_events
from zebra_agent_api.ag_ui_task_view import authorized_task_preflight, deadline_frames
from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_streaming import _deadline, tail_session_events, tail_task_events
from zebra_agent_api.stream_v2_reader import V2StreamContext
from zebra_agent_api.tenant_guard import task_access_response


def _problem(status: int, code: str) -> ApiResponse:
    return ApiResponse(status, {"code": code, "status": code})


def prepare_v2(
    api: ZebraAgentApi,
    path: str,
    query: Mapping[str, str],
    host: object,
) -> V2StreamContext | ApiResponse | None:
    reader = api.stream_v2_reader
    token = query.get("cursor") or query.get("after") or query.get("last_event_id")
    if reader is None and (token or "").startswith("v2."):
        return _problem(503, "stream_v2_unavailable")
    if host is None or getattr(api.stores, "deployment_namespace", None) is None:
        return _problem(503, "stream_v2_unavailable") if (token or "").startswith("v2.") else None
    parts = path.strip("/").split("/")
    try:
        if parts[0] == "agui":
            task_id, run_id, kind = TaskId(UUID(parts[2])), parts[4], "agui"
        elif parts[0] == "tasks":
            task_id, kind = TaskId(UUID(parts[1])), "task"
            run_id = api.stores.tasks.read_latest_run_header(task_id).run_id
        else:
            session_id = SessionId(UUID(parts[1]))
            resolved = api.stores.tasks.task_id_for_session(session_id)
            if resolved is None:
                return None
            task_id = resolved
            kind = "session"
            run_id = api.stores.tasks.read_latest_run_header(task_id).run_id
        if reader is None:
            from agent_integrations.run_stream_admission import load_run_stream_admission

            admission = load_run_stream_admission(api.stores.tasks, task_id, run_id)
            if admission is not None and admission.mode.value == "transient_v2":
                return _problem(503, "stream_v2_unavailable")
            return (
                _problem(503, "stream_v2_unavailable") if (token or "").startswith("v2.") else None
            )
        bound = reader.authority.bind(task_id, run_id, host)  # type: ignore[arg-type]
        if bound is None:
            return _problem(400, "invalid_cursor") if (token or "").startswith("v2.") else None
        return reader.context(
            bound,
            kind=kind,
            token=token,
            full_recovery=query.get("recovery") == "full",
            session_id=parts[1] if kind == "session" else None,
        )
    except CheckpointNotReady:
        if (token or "").startswith("v2."):
            return _problem(400, "invalid_cursor")
        # A bounded source proof distinguishes a new Task from broken executable metadata.
        try:
            if kind in {"session", "task"}:
                page = api.stores.tasks.read_event_page(task_id, 0, limit=256, max_bytes=1_048_576)
                if not page.has_more and not any(
                    entry.event.event_type is EventType.SESSION_COMMAND_ACCEPTED
                    for entry in page.events
                ):
                    return None
        except Exception:
            pass
        return _problem(409, "stream_source_unavailable")
    except ValueError:
        return _problem(400, "invalid_cursor")
    except Exception:
        return _problem(409, "stream_source_unavailable")


def _source_query(
    api: ZebraAgentApi, context: V2StreamContext, query: Mapping[str, str]
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
        observer = AgUiCheckpointObserver(api.stores.tasks, namespace=context.binding.namespace)
        observer.validate_cursor(
            observer.snapshot(context.binding.task_id, identity), identity, cursor
        )
        if cursor.frame_index is not None and cursor.frame_index > 0:
            cursor = cursor.model_copy(update={"frame_index": cursor.frame_index - 1})
        else:
            previous = api.stores.tasks.read_event_header(
                context.binding.task_id, cursor.sequence - 1
            )
            if previous is None:
                return result
            cursor = AgUiCursor(
                thread_id=cursor.thread_id,
                run_id=cursor.run_id,
                sequence=previous.task_sequence,
                event_id=str(previous.event_id),
            )
    result["cursor"] = cursor.encode()
    return result


def source_query(
    api: ZebraAgentApi, context: V2StreamContext, query: Mapping[str, str]
) -> dict[str, str] | ApiResponse:
    try:
        return _source_query(api, context, query)
    except ValueError:
        return _problem(400, "invalid_cursor")


async def agui_response(
    api: ZebraAgentApi, request: Request
) -> JSONResponse | StreamingResponse | None:
    host = getattr(request.state, "host_context", None)
    query = dict(request.query_params)
    if value := request.headers.get("Last-Event-ID"):
        query.setdefault("last_event_id", value)
    task_text = request.url.path.strip("/").split("/")[2]
    context = await authorized_task_preflight(
        lambda: task_access_response(api, task_text, host),
        lambda: prepare_v2(api, request.url.path, query, host),
        authorization_expires_at=getattr(host, "expires_at", None),
        request_deadline=getattr(request.state, "authorization_deadline", None),
    )
    if isinstance(context, ApiResponse):
        return JSONResponse(status_code=context.status_code, content=context.body)
    if isinstance(context, V2StreamContext):
        rewritten = await authorized_task_preflight(
            lambda: None,
            lambda: source_query(api, context, query),
            authorization_expires_at=getattr(host, "expires_at", None),
            request_deadline=getattr(request.state, "authorization_deadline", None),
        )
        if isinstance(rewritten, ApiResponse):
            return JSONResponse(status_code=rewritten.status_code, content=rewritten.body)
        query = rewritten
    prepared = await authorized_task_preflight(
        lambda: task_access_response(api, task_text, host),
        lambda: prepare_agui_stream(
            api.stores,
            request.url.path,
            query,
            live_event_fanout=api.live_event_fanout,
            deployment_namespace=getattr(api.stores, "deployment_namespace", None),
            authorization_expires_at=getattr(host, "expires_at", None),
            command_outcome=api.command_outcome,
            host_context=host,
            notifications=api.stream_notifications,
            recovery_notice=isinstance(context, V2StreamContext) and context.full_recovery,
        ),
        authorization_expires_at=getattr(host, "expires_at", None),
        request_deadline=getattr(request.state, "authorization_deadline", None),
    )
    if isinstance(prepared, ApiResponse):
        return JSONResponse(status_code=prepared.status_code, content=prepared.body)
    if not isinstance(prepared, AgUiStreamContext):
        return None
    stream = tail_agui_events(prepared, request)
    if isinstance(context, V2StreamContext):
        assert api.stream_v2_reader is not None
        stream = api.stream_v2_reader.tail(
            context,
            stream,
            deadline=_deadline(getattr(host, "expires_at", None)),
            disconnected=request.is_disconnected,
        )
    stream = deadline_frames(
        cast(AsyncGenerator[str, None], stream),
        _deadline(getattr(host, "expires_at", None)),
        authorization_expires_at=getattr(host, "expires_at", None),
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def raw_response(
    api: ZebraAgentApi,
    request: Request,
    *,
    database_path: Path,
) -> JSONResponse | StreamingResponse | None:
    host = getattr(request.state, "host_context", None)
    query = dict(request.query_params)
    if value := request.headers.get("Last-Event-ID"):
        query.setdefault("last_event_id", value)
    context = await authorized_task_preflight(
        lambda: None,
        lambda: prepare_v2(api, request.url.path, query, host),
        authorization_expires_at=getattr(host, "expires_at", None),
        request_deadline=getattr(request.state, "authorization_deadline", None),
    )
    if isinstance(context, ApiResponse):
        return JSONResponse(status_code=context.status_code, content=context.body)
    if context is None:
        return None
    if isinstance(context, V2StreamContext):
        rewritten = await authorized_task_preflight(
            lambda: None,
            lambda: source_query(api, context, query),
            authorization_expires_at=getattr(host, "expires_at", None),
            request_deadline=getattr(request.state, "authorization_deadline", None),
        )
        if isinstance(rewritten, ApiResponse):
            return JSONResponse(status_code=rewritten.status_code, content=rewritten.body)
        query = rewritten
    try:
        raw = query.get("after_sequence", query.get("last_event_id", "0"))
        after = int(raw)
        if after < 0:
            raise ValueError("negative cursor")
        resource = UUID(request.url.path.strip("/").split("/")[1])
    except ValueError:
        return JSONResponse(status_code=400, content={"status": "invalid_request"})
    deadline = _deadline(getattr(host, "expires_at", None))
    options = dict(
        database_path=database_path,
        stores=api.stores,
        request=request,
        live_event_fanout=api.live_event_fanout,
        deployment_namespace=getattr(api.stores, "deployment_namespace", None),
        authorization_expires_at=getattr(host, "expires_at", None),
        after_sequence=after,
        notifications=api.stream_notifications,
        recovery_notice=isinstance(context, V2StreamContext) and context.full_recovery,
    )
    if request.url.path.startswith("/tasks/"):
        task_id = TaskId(resource)
        header = await authorized_task_preflight(
            lambda: None,
            lambda: api.stores.tasks.read_task_header(
                task_id, require_source_coverage=api.settings.deployment != "local"
            ),
            authorization_expires_at=getattr(host, "expires_at", None),
            request_deadline=getattr(request.state, "authorization_deadline", None),
        )
        if isinstance(header, ApiResponse):
            return JSONResponse(status_code=header.status_code, content=header.body)
        if header is None:
            return JSONResponse(status_code=404, content={"status": "not_found"})
        if after > header.current_sequence:
            return JSONResponse(status_code=400, content={"status": "invalid_request"})
        stream = tail_task_events(task_id=task_id, **options)  # type: ignore[arg-type]
    else:
        session_id = SessionId(resource)
        if api.settings.deployment != "local":
            highwater = await authorized_task_preflight(
                lambda: None,
                lambda: api.stores.events.read_session_highwater(session_id),  # type: ignore[attr-defined]
                authorization_expires_at=getattr(host, "expires_at", None),
                request_deadline=getattr(request.state, "authorization_deadline", None),
            )
            if isinstance(highwater, ApiResponse):
                return JSONResponse(status_code=highwater.status_code, content=highwater.body)
            if after > highwater:
                return JSONResponse(status_code=400, content={"status": "invalid_request"})
        stream = tail_session_events(session_id=session_id, **options)  # type: ignore[arg-type]
    if isinstance(context, V2StreamContext):
        assert api.stream_v2_reader is not None
        stream = api.stream_v2_reader.tail(
            context, stream, deadline=deadline, disconnected=request.is_disconnected
        )
    stream = deadline_frames(
        cast(AsyncGenerator[str, None], stream),
        _deadline(getattr(host, "expires_at", None)),
        authorization_expires_at=getattr(host, "expires_at", None),
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
