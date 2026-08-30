"""Command-only AG-UI composition for the Embedded API boundary."""

from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from ag_ui.core import RunAgentInput
from agent_core.contracts import SessionCommandKind
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskId
from agent_storage import ControlPlaneStores
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator

from zebra_agent_api.responses import ApiResponse

_MAX_IDENTITY_TEXT = 256
_AGUI_COMMAND_PATH = "/agui/commands"


class _AgUiCommandApp(Protocol):
    stores: ControlPlaneStores

    @property
    def settings(self) -> object: ...

    def submit_command(
        self,
        session_id: str,
        payload: dict[str, object],
        *,
        idempotency_key: str | None,
    ) -> ApiResponse: ...


class AgUiCommandEnvelope(BaseModel):
    """Versioned transport envelope; ``input`` is the official AG-UI model."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)

    action: Literal["run", "resume", "stop"]
    thread_id: str = Field(
        validation_alias="threadId",
        serialization_alias="threadId",
        min_length=1,
        max_length=_MAX_IDENTITY_TEXT,
    )
    run_id: str = Field(
        validation_alias="runId",
        serialization_alias="runId",
        min_length=1,
        max_length=_MAX_IDENTITY_TEXT,
    )
    expected_revision: StrictInt = Field(
        validation_alias="expectedRevision",
        serialization_alias="expectedRevision",
        ge=0,
    )
    input: dict[str, object] | None = None

    @field_validator("thread_id", "run_id")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("AG-UI identity must not be blank")
        return normalized


def handle_agui_command(app: _AgUiCommandApp, request: object) -> ApiResponse | None:
    """Handle the AG-UI command paths without importing Worker execution code."""

    method = getattr(request, "method", "").upper()
    path = getattr(request, "path", "")
    if method != "POST":
        return None
    body = getattr(request, "body", None) or {}
    if not isinstance(body, dict):
        return _problem(400, "invalid_request", "request body must be an object", path)
    path_identity = _path_identity(path)
    if path_identity is None:
        return None
    try:
        if isinstance(path_identity, tuple):
            body = _with_path_identity(body, path_identity)
        envelope = AgUiCommandEnvelope.model_validate(body)
        task_id = TaskId(UUID(envelope.thread_id))
    except (ValidationError, ValueError) as exc:
        return _problem(400, "invalid_request", _safe_validation_detail(exc), path)

    task = app.stores.tasks.get_task(task_id)
    if task is None:
        return _problem(404, "not_found", "AG-UI thread was not found", path)
    if app.stores.sessions.get_session(task.active_segment_id) is None:
        return _problem(409, "projection_incomplete", "active Segment is unavailable", path)

    try:
        command_payload = _command_payload(envelope)
    except (TypeError, ValueError, ValidationError) as exc:
        return _problem(400, "invalid_request", _safe_validation_detail(exc), path)

    admission_error = _admit_client_mounts(app, command_payload, path)
    if admission_error is not None:
        return admission_error

    idempotency_key = _idempotency_key(request)
    if idempotency_key is None:
        return _problem(400, "missing_idempotency_key", "Idempotency-Key header is required", path)
    from zebra_agent_api.session_binding import renew_host_binding_for_command

    host_context = getattr(request, "host_context", None)
    if host_context is not None and not isinstance(host_context, HostContextEnvelope):
        return _problem(403, "host_binding_renewal_rejected", "Host context is invalid", path)
    renewal_error = renew_host_binding_for_command(
        app,
        str(task.task_id),
        host_context,
    )
    if renewal_error is not None:
        return _problem_from_response(renewal_error, path)
    response = app.submit_command(
        str(task.active_segment_id),
        {
            "kind": _command_kind(envelope.action).value,
            "expected_revision": envelope.expected_revision,
            "payload": command_payload,
        },
        idempotency_key=idempotency_key,
    )
    if response.status_code in {200, 202}:
        return _success(response, envelope)
    return _problem_from_response(response, path)


def _path_identity(path: str) -> str | tuple[str, str] | None:
    if path == _AGUI_COMMAND_PATH:
        return _AGUI_COMMAND_PATH
    parts = tuple(part for part in path.split("/") if part)
    if len(parts) == 5 and parts[:2] == ("agui", "threads") and parts[3] == "runs":
        return parts[2], parts[4]
    if (
        len(parts) == 6
        and parts[:2] == ("agui", "threads")
        and parts[3] == "runs"
        and parts[5] == "commands"
    ):
        return parts[2], parts[4]
    return None


def _with_path_identity(body: dict[str, object], identity: tuple[str, str]) -> dict[str, object]:
    result = dict(body)
    for key, value in (("threadId", identity[0]), ("runId", identity[1])):
        existing = result.get(key)
        if existing is not None and existing != value:
            raise ValueError(f"{key} does not match the AG-UI path")
        result[key] = value
    return result


def _command_payload(envelope: AgUiCommandEnvelope) -> dict[str, object]:
    payload: dict[str, object] = {
        "thread_id": envelope.thread_id,
        "run_id": envelope.run_id,
    }
    if envelope.action == "stop":
        if envelope.input is not None:
            raise ValueError("stop command must not include input")
        return payload

    candidate = dict(envelope.input or {})
    candidate.setdefault("threadId", envelope.thread_id)
    candidate.setdefault("runId", envelope.run_id)
    candidate.setdefault("state", {})
    candidate.setdefault("messages", [])
    candidate.setdefault("tools", [])
    candidate.setdefault("context", [])
    candidate.setdefault("forwardedProps", {})
    run_input = RunAgentInput.model_validate(candidate)
    if run_input.thread_id != envelope.thread_id or run_input.run_id != envelope.run_id:
        raise ValueError("input threadId/runId must match the command envelope")
    if envelope.action == "run" and run_input.resume is not None:
        raise ValueError("run command must not include input.resume")
    if envelope.action == "resume" and run_input.resume is None:
        raise ValueError("resume command requires input.resume")
    payload["input"] = run_input.model_dump(mode="json", by_alias=True, exclude_none=True)
    return payload


def _command_kind(action: str) -> SessionCommandKind:
    return {
        "run": SessionCommandKind.RUN,
        "resume": SessionCommandKind.RESUME,
        "stop": SessionCommandKind.STOP,
    }[action]


def _admit_client_mounts(
    app: _AgUiCommandApp, command_payload: dict[str, object], path: str
) -> ApiResponse | None:
    """Convert AG-UI tools/state into bounded client mount references.

    Disabled flag or absent platform: commands pass through unchanged.
    Enabled: the published frontend profile is the source of truth;
    undeclared tools, digest drift or handler code fail closed.
    """

    platform = getattr(app, "client_platform", None)
    capabilities = getattr(platform, "frontend_capabilities", None)
    run_input = command_payload.get("input")
    if capabilities is None or not isinstance(run_input, dict):
        return None
    forwarded = run_input.get("forwardedProps")
    forwarded = forwarded if isinstance(forwarded, dict) else {}
    frontend_app_id = forwarded.get("frontendAppId")
    profile = None
    if isinstance(frontend_app_id, str) and frontend_app_id.strip():
        profile = capabilities.get_latest_profile(frontend_app_id.strip())
    try:
        from agent_control_plane.agui_client_admission import (
            AgUiClientAdmissionError,
            admit_agui_client_payload,
        )

        admission = admit_agui_client_payload(
            tools=run_input.get("tools"),
            state=run_input.get("state"),
            profile=profile,
        )
    except AgUiClientAdmissionError as exc:
        return _problem(422, "client_admission_rejected", str(exc), path)
    except (TypeError, ValueError) as exc:
        return _problem(400, "invalid_request", _safe_validation_detail(exc), path)
    command_payload["client"] = {
        "mounted_tools": list(admission.mounted_tools),
        "state_digest": admission.state_digest,
        "state_bytes": admission.state_bytes,
        "redacted_keys": list(admission.redacted_keys),
        "frontend_app_id": frontend_app_id if isinstance(frontend_app_id, str) else None,
        "profile_digest": profile.profile_digest if profile is not None else None,
    }
    return None


def _idempotency_key(request: object) -> str | None:
    headers = getattr(request, "headers", None) or {}
    for name, value in headers.items():
        if name.lower() == "idempotency-key" and isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _success(response: ApiResponse, envelope: AgUiCommandEnvelope) -> ApiResponse:
    body = dict(response.body)
    body.update(
        {
            "threadId": envelope.thread_id,
            "runId": envelope.run_id,
            "action": envelope.action,
        }
    )
    return ApiResponse(response.status_code, body)


def _problem_from_response(response: ApiResponse, path: str) -> ApiResponse:
    status_text = response.body.get("status")
    code = status_text if isinstance(status_text, str) else "command_rejected"
    detail = response.body.get("reason")
    if not isinstance(detail, str) or not detail:
        detail = "AG-UI command was rejected"
    return _problem(response.status_code, code, detail, path)


def _problem(status: int, code: str, detail: str, path: str) -> ApiResponse:
    return ApiResponse(
        status,
        {
            "type": f"https://zebra.invalid/problems/{code}",
            "title": "AG-UI command rejected",
            "status": status,
            "detail": detail[:512],
            "instance": path,
            "code": code,
        },
    )


def _safe_validation_detail(error: BaseException) -> str:
    if isinstance(error, ValidationError):
        details = error.errors()
        if not details:
            return "request validation failed"
        message = details[0]["msg"]
        return message if isinstance(message, str) else "request validation failed"
    return str(error)[:512] or "request validation failed"
