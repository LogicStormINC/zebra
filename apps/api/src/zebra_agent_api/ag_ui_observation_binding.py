"""Current observer authority and exact public slice/cursor composition."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_integrations.ag_ui.profiles import AgUiProfileRegistry, AgUiProjectionProfile
from agent_integrations.ag_ui.standard_state import StandardProjectionState

from zebra_agent_api.ag_ui_public_binding import (
    AgUiPublicSlice,
    resolve_public_slice,
    standard_state_after,
)
from zebra_agent_api.ag_ui_stream import AgUiStreamContext
from zebra_agent_api.client_approval_operations import _current
from zebra_agent_api.responses import ApiResponse


def public_slice_for_request(
    api: Any,
    request: Any,
    host: Any,
    profile: AgUiProjectionProfile,
    task: TaskId,
    internal: str,
) -> AgUiPublicSlice | ApiResponse:
    try:
        segment = SessionId(UUID(request.headers.get("X-Zebra-Command-Segment", "")))
        denied = _current(
            api,
            SimpleNamespace(
                headers=dict(request.headers),
                host_context=host,
                verified_host_grant=getattr(request.state, "verified_host_grant", None),
            ),
            task,
            internal,
            segment,
            write=False,
        )
        if isinstance(denied, ApiResponse):
            return denied
        source = api.stores.tasks.read_event_header_by_key(
            task, segment, request.headers.get("Idempotency-Key", "")
        )
        if source is None:
            raise CheckpointNotReady("original operation is not observed")
        public = resolve_public_slice(
            api.stores.tasks,
            namespace=getattr(api.stores, "deployment_namespace", None) or "local",
            task_id=task,
            internal_run_id=internal,
            source=source,
            profile=profile,
        )
        return public if public is not None else ApiResponse(409, {"status": "no_public_successor"})
    except CheckpointNotReady:
        return ApiResponse(409, {"status": "projection_not_ready", "retryable": True})
    except (ValueError, TypeError):
        return ApiResponse(409, {"status": "agui_observation_conflict"})


def validate_public_cursor(api: Any, prepared: AgUiStreamContext, public: AgUiPublicSlice) -> bool:
    if prepared.cursor is None:
        return False
    position = prepared.cursor.sequence
    if position < public.source.task_sequence - 1:
        raise ValueError("cursor precedes requested public slice")
    if position >= public.source.task_sequence:
        run = api.stores.tasks.read_run_header(public.scope.task_id, public.internal_run_id)
        header = api.stores.tasks.read_event_header(public.scope.task_id, position)
        if header is None:
            raise ValueError("cursor source is unavailable")
        state = standard_state_after(api.stores.tasks, public.scope, run, header)
        if state.protocol_run_id != public.run_id:
            raise ValueError("cursor belongs to another public slice")
        if state.turn_finished:
            frame = api.stores.tasks.read_event_projection_header(public.scope, position)
            if frame is None:
                raise CheckpointNotReady("public terminal frame is not ready")
            return (
                prepared.cursor.frame_index is None
                or prepared.cursor.frame_index == frame.frame_count - 1
            )
    return False


def requested_profile(api: Any, request: Any) -> AgUiProjectionProfile | ApiResponse | None:
    try:
        return (api.agui_profiles or AgUiProfileRegistry()).select(
            request.headers.get("X-Zebra-AGUI-Profile")
        )
    except ValueError:
        return ApiResponse(409, {"status": "agui_profile_unavailable"})


def request_public_slice(
    api: Any, request: Any, host: Any, profile: AgUiProjectionProfile | None
) -> AgUiPublicSlice | ApiResponse | None:
    if profile is None or not issubclass(profile.state_type, StandardProjectionState):
        return None
    parts = request.url.path.strip("/").split("/")
    return public_slice_for_request(api, request, host, profile, TaskId(UUID(parts[2])), parts[4])


def stream_negotiation_problem(status: int, code: str) -> ApiResponse:
    return ApiResponse(
        status,
        {
            "code": code,
            "status": code,
            **({"retryable": True} if status == 409 and code == "projection_not_ready" else {}),
        },
    )
