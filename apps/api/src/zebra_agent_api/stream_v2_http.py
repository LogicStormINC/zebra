"""Read-only stream negotiation after the existing signed Host/tenant boundary."""

from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import nullcontext
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from agent_core.domain.events import EventType
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.stream_source_head import StreamObservationReadPort
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_integrations.ag_ui import AgUiCursor
from agent_storage.live_event_store import PostCommitPublishingEventStore
from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
from agent_storage.postgres.direct_control import PostgresDirectControl
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.projections import PostgresProjectionStore
from agent_storage.postgres.stream_proof_batch import StreamProofSnapshot
from agent_storage.postgres.task_io import current_task_io_deadline
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from zebra_agent_api.ag_ui_stream import AgUiStreamContext, prepare_agui_stream, tail_agui_events
from zebra_agent_api.ag_ui_task_view import (
    _check_read_deadline,
    authorized_task_preflight,
    deadline_frames,
)
from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_streaming import _deadline, tail_session_events, tail_task_events
from zebra_agent_api.stream_v2_authority import V2ReadAuthority, V2ReadBinding
from zebra_agent_api.stream_v2_reader import V2StreamContext
from zebra_agent_api.tenant_guard import task_access_response


def _problem(status: int, code: str) -> ApiResponse:
    return ApiResponse(status, {"code": code, "status": code})


def _native_raw_authority(api: ZebraAgentApi) -> V2ReadAuthority | None:
    authority = getattr(getattr(api, "stream_v2_reader", None), "authority", None)
    tasks = getattr(api.stores, "tasks", None)
    if (
        type(authority) is V2ReadAuthority
        and type(tasks) is PostgresAgentTaskStore
        and tasks.stream_head_reads_compatible
        and authority.stores.tasks is tasks
        and authority.dsn == tasks._database._dsn
        and authority.namespace == getattr(api.stores, "deployment_namespace", None)
        and authority.namespace == tasks._database.deployment_namespace
    ):
        for target, name, original in (
            (authority, "bind", V2ReadAuthority._snapshot_native_bind),
            (authority, "bind_snapshot", V2ReadAuthority._snapshot_native_bind_snapshot),
            (tasks, "read_stream_source_head", PostgresAgentTaskStore._snapshot_native_source_head),
            (
                tasks,
                "read_stream_checkpoint_head",
                PostgresAgentTaskStore._snapshot_native_checkpoint_head,
            ),
        ):
            method = getattr(target, name)
            if getattr(method, "__func__", method) is not original:
                return None
        return authority
    return None


def _raw_snapshot_authority(api: ZebraAgentApi) -> V2ReadAuthority | None:
    if prepare_v2 is not _native_agui_callbacks[1]:
        return None
    authority = _native_raw_authority(api)
    if authority is None:
        return None
    control, sessions, events = api.cloud_control, api.stores.sessions, api.stores.events
    if type(events) is PostCommitPublishingEventStore:
        method = events.read_session_highwater
        if (
            getattr(method, "__func__", method)
            is not PostCommitPublishingEventStore._snapshot_native_highwater
        ):
            return None
        events = events._event_store
    if (
        type(control) is not PostgresDirectControl
        or not control.supports_binding_snapshot(authority.proofs._database)
        or type(sessions) is not PostgresProjectionStore
        or type(events) is not PostgresEventStore
    ):
        return None
    namespace_method = sessions.get_session_namespace
    highwater_method = events.read_session_highwater
    if (
        getattr(namespace_method, "__func__", namespace_method)
        is not PostgresProjectionStore._snapshot_native_namespace
        or getattr(highwater_method, "__func__", highwater_method)
        is not PostgresEventStore._snapshot_native_highwater
    ):
        return None
    for database in (sessions._database, events._database):
        if database._dsn != authority.dsn or database.deployment_namespace != authority.namespace:
            return None
    return authority


def prepare_v2(
    api: ZebraAgentApi,
    path: str,
    query: Mapping[str, str],
    host: object,
    *,
    proof: StreamProofSnapshot | None = None,
) -> V2StreamContext | ApiResponse | None:
    reader = api.stream_v2_reader
    token = query.get("cursor") or query.get("after") or query.get("last_event_id")
    if reader is None and (token or "").startswith("v2."):
        return _problem(503, "stream_v2_unavailable")
    if host is None or getattr(api.stores, "deployment_namespace", None) is None:
        return _problem(503, "stream_v2_unavailable") if (token or "").startswith("v2.") else None
    parts = path.strip("/").split("/")
    try:
        authority = _native_raw_authority(api) if parts[0] != "agui" or proof is not None else None
        if proof is not None and (
            authority is None
            or proof._database._dsn != authority.dsn
            or proof._database.deployment_namespace != authority.namespace
        ):
            raise ValueError("stream snapshot crosses request database scope")
        scope = (
            authority.proofs.snapshot()
            if authority is not None and proof is None
            else nullcontext(proof)
        )
        with scope as proof:
            tasks = proof if proof is not None else api.stores.tasks
            if parts[0] == "agui":
                task_id, run_id, kind = TaskId(UUID(parts[2])), parts[4], "agui"
            elif parts[0] == "tasks":
                task_id, kind = TaskId(UUID(parts[1])), "task"
                run_id = tasks.read_latest_run_header(task_id).run_id
            else:
                session_id = SessionId(UUID(parts[1]))
                resolved = tasks.task_id_for_session(session_id)
                if resolved is None:
                    return None
                task_id = resolved
                kind = "session"
                run_id = tasks.read_latest_run_header(task_id).run_id
            if reader is None:
                from agent_integrations.run_stream_admission import load_run_stream_admission

                admission = load_run_stream_admission(api.stores.tasks, task_id, run_id)
                if admission is not None and admission.mode.value == "transient_v2":
                    return _problem(503, "stream_v2_unavailable")
                return (
                    _problem(503, "stream_v2_unavailable")
                    if (token or "").startswith("v2.")
                    else None
                )
            bound = (
                reader.authority.bind_snapshot(
                    proof, task_id, run_id, cast(HostContextEnvelope, host)
                )
                if proof is not None
                else reader.authority.bind(task_id, run_id, cast(HostContextEnvelope, host))
            )
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
            api.stores.tasks, namespace=context.binding.namespace, initial_metadata=initial_metadata
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
        return _problem(400, "invalid_cursor")


_native_agui_callbacks = (task_access_response, prepare_v2, source_query, prepare_agui_stream)


def _agui_snapshot_authority(api: ZebraAgentApi) -> V2ReadAuthority | None:
    if any(
        current is not original
        for current, original in zip(
            (task_access_response, prepare_v2, source_query, prepare_agui_stream),
            _native_agui_callbacks,
            strict=True,
        )
    ):
        return None
    authority = _raw_snapshot_authority(api)
    if authority is None:
        return None
    return authority


async def agui_response(
    api: ZebraAgentApi, request: Request
) -> JSONResponse | StreamingResponse | None:
    host = getattr(request.state, "host_context", None)
    query = dict(request.query_params)
    if value := request.headers.get("Last-Event-ID"):
        query.setdefault("last_event_id", value)
    task_text = request.url.path.strip("/").split("/")[2]

    authority = _agui_snapshot_authority(api)

    def prepare_context(
        proof: StreamProofSnapshot | None = None,
    ) -> tuple[V2StreamContext | None, AgUiStreamContext | None] | ApiResponse:
        context = (
            prepare_v2(api, request.url.path, query, host, proof=proof)
            if proof is not None
            else prepare_v2(api, request.url.path, query, host)
        )
        if isinstance(context, ApiResponse):
            return context
        rewritten = (
            (
                source_query(api, context, query, initial_metadata=proof)
                if proof is not None
                else source_query(api, context, query)
            )
            if isinstance(context, V2StreamContext)
            else query
        )
        if isinstance(rewritten, ApiResponse):
            return rewritten
        metadata: dict[str, Any] = {"initial_metadata": proof} if proof is not None else {}
        if (
            proof is not None
            and isinstance(context, V2StreamContext)
            and type(context.binding) is V2ReadBinding
        ):
            metadata["source_qualified_task"] = context.binding.task_id
        prepared = prepare_agui_stream(
            api.stores,
            request.url.path,
            rewritten,
            live_event_fanout=api.live_event_fanout,
            deployment_namespace=getattr(api.stores, "deployment_namespace", None),
            authorization_expires_at=getattr(host, "expires_at", None),
            command_outcome=api.command_outcome,
            host_context=host,
            notifications=api.stream_notifications,
            recovery_notice=isinstance(context, V2StreamContext) and context.full_recovery,
            **metadata,
        )
        return prepared if isinstance(prepared, ApiResponse) else (context, prepared)

    def prepare() -> tuple[V2StreamContext | None, AgUiStreamContext | None] | ApiResponse:
        if authority is None:
            return prepare_context()
        with authority.proofs.snapshot() as proof:
            denied = task_access_response(api, task_text, host, proof=proof)
            _check_read_deadline(current_task_io_deadline(), getattr(host, "expires_at", None))
            return denied if denied is not None else prepare_context(proof)

    admitted = await authorized_task_preflight(
        (lambda: task_access_response(api, task_text, host)) if authority is None else lambda: None,
        prepare,
        authorization_expires_at=getattr(host, "expires_at", None),
        request_deadline=getattr(request.state, "authorization_deadline", None),
    )
    if isinstance(admitted, ApiResponse):
        return JSONResponse(status_code=admitted.status_code, content=admitted.body)
    context, prepared = admitted
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
    preflight: Callable[[], ApiResponse | None] | None = None,
    snapshot_preflight: Callable[[StreamProofSnapshot], ApiResponse | None] | None = None,
) -> JSONResponse | StreamingResponse | None:
    host = getattr(request.state, "host_context", None)
    query = dict(request.query_params)
    if value := request.headers.get("Last-Event-ID"):
        query.setdefault("last_event_id", value)

    authority = _raw_snapshot_authority(api) if snapshot_preflight is not None else None

    def prepare_context(
        proof: StreamProofSnapshot | None = None,
    ) -> ApiResponse | tuple[V2StreamContext, dict[str, str], UUID, int] | None:
        context = (
            prepare_v2(api, request.url.path, query, host, proof=proof)
            if proof is not None
            else prepare_v2(api, request.url.path, query, host)
        )
        if isinstance(context, ApiResponse) or context is None:
            return context
        rewritten = source_query(api, context, query)
        if isinstance(rewritten, ApiResponse):
            return rewritten
        try:
            raw = rewritten.get("after_sequence", rewritten.get("last_event_id", "0"))
            after = int(raw)
            if after < 0:
                raise ValueError("negative cursor")
            resource = UUID(request.url.path.strip("/").split("/")[1])
        except ValueError:
            return ApiResponse(400, {"status": "invalid_request"})
        if request.url.path.startswith("/tasks/"):
            header = (proof if proof is not None else api.stores.tasks).read_task_header(
                TaskId(resource), require_source_coverage=api.settings.deployment != "local"
            )
            if header is None:
                return ApiResponse(404, {"status": "not_found"})
            highwater = header.current_sequence
        elif api.settings.deployment != "local":
            if proof is not None:
                highwater = proof.read_session_highwater(SessionId(resource))
            else:
                highwater = api.stores.events.read_session_highwater(SessionId(resource))  # type: ignore[attr-defined]
        else:
            highwater = after
        if after > highwater:
            return ApiResponse(400, {"status": "invalid_request"})
        return context, rewritten, resource, after

    def prepare() -> ApiResponse | tuple[V2StreamContext, dict[str, str], UUID, int] | None:
        if authority is None or snapshot_preflight is None:
            return prepare_context()
        with authority.proofs.snapshot() as proof:
            denied = snapshot_preflight(proof)
            _check_read_deadline(current_task_io_deadline(), getattr(host, "expires_at", None))
            return denied if denied is not None else prepare_context(proof)

    admitted = await authorized_task_preflight(
        preflight if authority is None and preflight is not None else lambda: None,
        prepare,
        authorization_expires_at=getattr(host, "expires_at", None),
        request_deadline=getattr(request.state, "authorization_deadline", None),
    )
    if isinstance(admitted, ApiResponse):
        return JSONResponse(status_code=admitted.status_code, content=admitted.body)
    if admitted is None:
        return None
    context, query, resource, after = admitted
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
        stream = tail_task_events(task_id=TaskId(resource), **options)  # type: ignore[arg-type]
    else:
        stream = tail_session_events(session_id=SessionId(resource), **options)  # type: ignore[arg-type]
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
