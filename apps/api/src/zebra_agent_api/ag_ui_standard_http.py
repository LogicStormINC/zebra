"""Official RunAgentInput POST observes one pre-admitted public slice, never executes."""

from collections.abc import AsyncIterator
from dataclasses import replace
from math import isfinite
from typing import Any
from uuid import UUID

from ag_ui.core import RunAgentInput, RunErrorEvent
from ag_ui.encoder import EventEncoder
from agent_core.contracts.session_commands import validate_accepted_session_command
from agent_core.domain.client_context import validate_client_state_json
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_integrations.ag_ui.profiles import AgUiProfileRegistry
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from zebra_agent_api.ag_ui_observation_binding import (
    public_slice_for_request,
    validate_public_cursor,
)
from zebra_agent_api.ag_ui_stream import AgUiStreamContext, prepare_agui_stream, tail_agui_events
from zebra_agent_api.ag_ui_task_view import authorized_task_preflight
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.tenant_guard import task_access_response


def accepted_input(
    tasks: Any,
    task: TaskId,
    source: Any,
    *,
    client_session_id: str | None = None,
    interaction: bool = False,
    native_run_id: str | None = None,
    projection_version: str | None = None,
) -> RunAgentInput:
    """Read precisely one immutable accepted Event; no command-ID/Event-ID equivalence."""
    page = tasks.read_event_page(
        task,
        source.task_sequence - 1,
        limit=1,
        max_bytes=1_048_576,
        through_sequence=source.task_sequence,
    )
    if len(page.events) != 1:
        raise ValueError("accepted command input is unavailable")
    entry = page.events[0]
    if (entry.task_sequence, entry.event.event_id, entry.segment_id, entry.segment_sequence) != (
        source.task_sequence,
        source.event_id,
        source.segment_id,
        source.segment_sequence,
    ):
        raise ValueError("accepted command coordinate conflicts")
    if entry.event.event_type is EventType.SESSION_COMMAND_ACCEPTED:
        command = validate_accepted_session_command(
            entry.event.payload,
            session_id=source.segment_id,
            idempotency_key=entry.event.idempotency_key,
        )
        payload = command.payload
    elif interaction and entry.event.event_type in {
        EventType.APPROVAL_REJECTED,
        EventType.SESSION_CANCELLED,
    }:
        payload = entry.event.payload
    else:
        raise ValueError("accepted command coordinate conflicts")
    preparation = payload.get("client_preparation") if interaction else None
    if isinstance(preparation, dict):
        from agent_core.domain.client_preparation import ClientPreparationContext

        context = ClientPreparationContext.model_validate(
            {**preparation, "input": payload.get("input")}
        )
        if (
            context.task_id != task
            or context.run_id != native_run_id
            or context.projection_version != projection_version
        ):
            raise ValueError("original native interaction target conflicts")
        if str(context.client_session_id) != client_session_id:
            raise PermissionError("private interaction belongs to another Client Session")
        return RunAgentInput.model_validate(context.input)
    if client_session_id is not None:
        original = payload.get("agui_native_preparation")
        mounted = payload.get("client")
        owner = (
            original.get("client_session_id")
            if isinstance(original, dict) and original.get("version") == 1
            else mounted.get("client_session_id")
            if isinstance(mounted, dict)
            and mounted.get("client_state_admission_contract_version") == 1
            else None
        )
        if owner != client_session_id:
            raise PermissionError("private admitted input belongs to another Client Session")
    raw_input = payload.get("input")
    if not isinstance(raw_input, dict):
        raise ValueError("accepted command has no standard input")
    candidate = dict(raw_input)
    candidate.setdefault("threadId", str(task))
    candidate.setdefault("runId", payload.get("run_id"))
    candidate.setdefault("context", [])
    candidate.setdefault("tools", [])
    candidate.setdefault("forwardedProps", {})
    return RunAgentInput.model_validate(candidate)


def observation_target(path: str, body: object) -> tuple[TaskId, str, RunAgentInput]:
    parts = path.strip("/").split("/")
    if (
        len(parts) != 6
        or parts[:2] != ["agui", "threads"]
        or parts[3] != "runs"
        or parts[5] != "stream"
    ):
        raise ValueError("invalid standard observation target")
    value = RunAgentInput.model_validate(body)
    validate_client_state_json(value.model_dump(mode="json", by_alias=True, exclude_none=True))
    task = TaskId(UUID(parts[2]))
    if value.protocol_version not in {None, "1.0"}:
        raise ValueError("standard observation requires protocol 1.0")
    if value.thread_id != str(task) or len(parts[4]) > 256 or not parts[4]:
        raise ValueError("standard observation thread conflicts")
    return task, parts[4], value


async def standard_response(
    api: Any, request: Request, body: object
) -> JSONResponse | StreamingResponse:
    host = getattr(request.state, "host_context", None)

    def prepare() -> tuple[AgUiStreamContext, Any] | ApiResponse:
        try:
            task, internal, incoming = observation_target(request.url.path, body)
            profile = (api.agui_profiles or AgUiProfileRegistry()).select(
                request.headers.get("X-Zebra-AGUI-Profile"),
                request.headers.get("X-Zebra-AGUI-Revision"),
            )
            if profile is None:
                return ApiResponse(409, {"status": "agui_profile_unavailable"})
            reliable = profile.profile_id == "zebra-reliable-v2-agui-1.0"
            if not reliable and (request.query_params or request.headers.get("Last-Event-ID")):
                raise ValueError("standard observation does not accept replay cursors")
            denied = task_access_response(
                api,
                str(task),
                host,
                verified_host_grant=getattr(request.state, "verified_host_grant", None),
                run_id=internal,
            )
            if denied is not None:
                return denied
            public = public_slice_for_request(api, request, host, profile, task, internal)
            if isinstance(public, ApiResponse):
                return public
            if incoming.run_id != public.run_id:
                raise ValueError("requested public Run is not the admitted operation")
            from zebra_agent_api.client_grant_auth import SessionBackedClientGrantAuthorizer

            auth = SessionBackedClientGrantAuthorizer(
                api.client_platform.client_sessions
            ).authorize(
                dict(request.headers),
                host_context=host,
                require_host_context=api.settings.deployment == "cloud",
                verified_host_grant=getattr(request.state, "verified_host_grant", None),
            )
            if auth is None:
                return ApiResponse(401, {"status": "client_session_authorization_required"})
            accepted = accepted_input(
                api.stores.tasks,
                task,
                public.source,
                client_session_id=str(auth.client_session_id),
                interaction=profile.revision == 2,
                native_run_id=internal,
                projection_version=public.scope.projector_version,
            )
            if (accepted.run_id != internal and profile.revision != 2) or accepted.thread_id != str(
                task
            ):
                raise ValueError("accepted input belongs to another native Run")
            if not _same_json(
                incoming.model_dump(mode="json", exclude={"run_id"}),
                accepted.model_dump(mode="json", exclude={"run_id"}),
            ):
                raise ValueError("standard input differs from original admitted input")
            from zebra_agent_api.stream_v2_http import prepare_v2, source_query

            query = dict(request.query_params)
            if token := request.headers.get("Last-Event-ID"):
                query.setdefault("last_event_id", token)
            transport = (
                prepare_v2(api, request.url.path, query, host, profile=profile)
                if reliable
                else None
            )
            if isinstance(transport, ApiResponse):
                return transport
            rewritten = source_query(api, transport, query) if transport is not None else {}
            if isinstance(rewritten, ApiResponse):
                return rewritten
            prepared = prepare_agui_stream(
                api.stores,
                request.url.path,
                rewritten,
                live_event_fanout=api.live_event_fanout,
                command_outcome=api.command_outcome,
                notifications=api.stream_notifications,
                deployment_namespace=getattr(api.stores, "deployment_namespace", None),
                authorization_expires_at=getattr(host, "expires_at", None),
                host_context=host,
                requested_profile=profile.profile_id,
                requested_revision=str(profile.revision),
                profile_registry=api.agui_profiles,
            )
            if not isinstance(prepared, AgUiStreamContext):
                return prepared or ApiResponse(404, {"status": "not_found"})
            exhausted = validate_public_cursor(api, prepared, public)
            return replace(
                prepared, public_slice=public, public_cursor_exhausted=exhausted
            ), transport
        except PermissionError:
            return ApiResponse(403, {"status": "agui_input_scope_denied"})
        except CheckpointNotReady:
            return ApiResponse(409, {"status": "projection_not_ready", "retryable": True})
        except (ValueError, TypeError):
            return ApiResponse(409, {"status": "agui_observation_conflict"})

    prepared = await authorized_task_preflight(
        lambda: None,
        prepare,
        authorization_expires_at=getattr(host, "expires_at", None),
        request_deadline=getattr(request.state, "authorization_deadline", None),
    )
    if isinstance(prepared, ApiResponse):
        return JSONResponse(status_code=prepared.status_code, content=prepared.body)
    context, transport = prepared
    stream = tail_agui_events(context, request)
    if transport is not None:
        from zebra_agent_api.session_streaming import _deadline

        stream = api.stream_v2_reader.tail(
            transport,
            stream,
            deadline=_deadline(getattr(host, "expires_at", None)),
            disconnected=request.is_disconnected,
        )
    else:
        stream = standard_frames(stream, request)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def standard_frames(source: AsyncIterator[str], request: Request) -> AsyncIterator[str]:
    """Observation failure is a protocol error, without inventing a durable Task failure."""
    from zebra_agent_api.stream_v2_wire import parse_record

    terminal = False
    try:
        async for record in source:
            _, event = parse_record(record)
            if event.get("type") == "CUSTOM" and (
                str(event.get("name", "")).startswith("zebra.stream.")
                or event.get("name") == "zebra.observation.problem"
            ):
                if event.get("name") == "zebra.observation.problem":
                    yield EventEncoder().encode(
                        RunErrorEvent(
                            message="AG-UI observation is unavailable",
                            code="observation_unavailable",
                        )
                    )
                    return
                continue
            yield record
            if event.get("type") in {"RUN_FINISHED", "RUN_ERROR"}:
                terminal = True
                return
    except Exception:
        pass  # Convert failed observation only; canonical execution facts stay unchanged.
    finally:
        close = getattr(source, "aclose", None)
        if close is not None:
            await close()
    if not terminal and not await request.is_disconnected():
        yield EventEncoder().encode(
            RunErrorEvent(
                message="AG-UI observation ended before its terminal", code="observation_incomplete"
            )
        )


def _same_json(left: Any, right: Any) -> bool:
    """JSON numbers compare numerically; booleans remain a different JSON type."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, int | float) and isinstance(right, int | float):
        return (
            (isinstance(left, int) or isfinite(left))
            and (isinstance(right, int) or isfinite(right))
            and left == right
        )
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _same_json(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_json(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)
