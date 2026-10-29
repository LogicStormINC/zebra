"""Explicit native MESSAGE admission, followed by read-only public binding lookup."""

from typing import Any
from uuid import UUID

from ag_ui.core import RunAgentInput
from agent_core.domain.client_context import validate_client_state_json
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_integrations.ag_ui.profiles import AgUiProfileRegistry
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from zebra_agent_api.ag_ui_command import _admit_client_mounts, _idempotency_key
from zebra_agent_api.ag_ui_public_binding import resolve_public_continuation
from zebra_agent_api.ag_ui_standard_http import accepted_input
from zebra_agent_api.client_approval_operations import _current
from zebra_agent_api.responses import ApiResponse


class AgUiMessagePreparation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: StrictInt = Field(alias="expectedRevision", ge=0)
    input: RunAgentInput


def prepare_target(path: str) -> tuple[TaskId, str, str] | None:
    parts = path.strip("/").split("/")
    if (
        len(parts) != 6
        or parts[:2] != ["agui", "threads"]
        or parts[3] != "runs"
        or parts[5] not in {"prepare", "prepared"}
    ):
        return None
    if not parts[4] or len(parts[4]) > 256:
        raise ValueError("invalid native Run target")
    return TaskId(UUID(parts[2])), parts[4], parts[5]


def handle_agui_prepare(
    app: Any, request: Any, *, extension_admission: Any = None
) -> ApiResponse | None:
    try:
        target = prepare_target(request.path)
        if target is None:
            return None
        task, internal, action = target
        if request.method != ("POST" if action == "prepare" else "GET"):
            return ApiResponse(405, {"status": "method_not_allowed"})
        if request.query or action == "prepared" and request.body is not None:
            raise ValueError("unexpected preparation input")
        headers = {k.lower(): v for k, v in (request.headers or {}).items()}
        segment = SessionId(UUID(headers.get("x-zebra-command-segment", "")))
        key = _idempotency_key(request)
        if key is None or len(key) > 256:
            raise ValueError("original Idempotency-Key is required")
        profile = (app.agui_profiles or AgUiProfileRegistry()).select(
            headers.get("x-zebra-agui-profile"), headers.get("x-zebra-agui-revision")
        )
        if profile is None:
            return ApiResponse(409, {"status": "agui_profile_unavailable"})
        denied = _current(
            app, request, task, internal, segment, write=action == "prepare", canonical=False
        )
        if isinstance(denied, ApiResponse):
            return denied
        client_auth = denied
        if action == "prepare":
            session = app.stores.sessions.get_session(segment)
            if session is None or session.status is not SessionStatus.AWAITING_TURN:
                return ApiResponse(409, {"status": "agui_message_not_ready"})
            prepared = AgUiMessagePreparation.model_validate(request.body)
            value = prepared.input
            if value.protocol_version not in {None, "1.0"}:
                raise ValueError("standard native admission requires protocol 1.0")
            value = value.model_copy(update={"protocol_version": "1.0"})
            validate_client_state_json(
                value.model_dump(mode="json", by_alias=True, exclude_none=True)
            )
            if value.thread_id != str(task) or value.run_id != internal or value.resume is not None:
                raise ValueError("native message input target conflicts")
            if not value.messages or value.messages[-1].role != "user":
                raise ValueError("native MESSAGE requires a final user message")
            content = value.messages[-1].content
            if not isinstance(content, str) or not content.strip():
                raise ValueError("native MESSAGE requires nonblank text content")
            payload: dict[str, object] = {
                "thread_id": str(task),
                "run_id": internal,
                "content": content,
                "input": value.model_dump(mode="json", by_alias=True, exclude_none=True),
            }
            denied = _admit_client_mounts(app, payload, request.path, request=request)
            if denied is not None:
                return denied
            client = payload.get("client")
            validated_client = (
                payload.pop("client")
                if isinstance(client, dict) and "client_state_admission_contract_version" in client
                else None
            )
            response: ApiResponse = app.submit_command(
                str(segment),
                {
                    "kind": "message",
                    "expected_revision": prepared.expected_revision,
                    "payload": payload,
                },
                idempotency_key=key,
                extension_admission=extension_admission,
                verified_host_grant=request.verified_host_grant,
                native_input_owner=client_auth.client_session_id,
                **(
                    {"validated_client_admission": validated_client}
                    if validated_client is not None
                    else {}
                ),
            )
            if response.status_code not in {200, 202}:
                return response
            # Keep the original native receipt even while the public projector lags.
            receipt = dict(response.body)
        else:
            receipt = {}
        source = app.stores.tasks.read_event_header_by_key(task, segment, key)
        if source is None:
            return ApiResponse(202, {"status": "binding_pending", "receipt": receipt})
        resolution = resolve_public_continuation(
            app.stores.tasks,
            namespace=getattr(app.stores, "deployment_namespace", None) or "local",
            task_id=task,
            internal_run_id=internal,
            source=source,
            profile=profile,
        )
        if resolution.slice is None:
            return ApiResponse(
                200,
                {
                    "status": resolution.kind,
                    "runId": resolution.protocol_run_id,
                    "turnFinished": resolution.turn_finished,
                    "executionStatus": resolution.status,
                    "receipt": receipt,
                },
            )
        public = resolution.slice
        value = accepted_input(
            app.stores.tasks, task, source, client_session_id=str(client_auth.client_session_id)
        )
        # This is explicit metadata from the accepted operation. The native authority
        # coordinate stays in BFF server context and is never placed in public state.
        return ApiResponse(
            200,
            {
                "status": "prepared",
                "threadId": str(task),
                "runId": public.run_id,
                "previousRunId": public.previous_run_id,
                "receipt": receipt,
                "input": value.model_copy(update={"run_id": public.run_id}).model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
            },
        )
    except PermissionError:
        return ApiResponse(403, {"status": "agui_input_scope_denied"})
    except CheckpointNotReady:
        return ApiResponse(202, {"status": "binding_pending"})
    except (ValueError, TypeError):
        return ApiResponse(409, {"status": "agui_preparation_conflict"})
