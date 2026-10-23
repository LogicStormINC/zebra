"""Exact approval/continuation receipt. Reads observe; they never repair or resubmit."""

import hashlib
import json
import re
from time import monotonic
from typing import Any, Literal
from uuid import UUID, uuid4

from agent_core.application import (
    ApprovalDecisionAction,
    ApprovalDecisionCommand,
    ApprovalDecisionService,
)
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.client_sessions import ClientControlFence
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.client_approval_operations import ClientApprovalOperationPort
from agent_storage.postgres.task_io import task_io_deadline
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from zebra_agent_api.client_grant_auth import SessionBackedClientGrantAuthorizer
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.tenant_guard import task_access_response

_ROUTE = re.compile(r"/v1/tasks/([^/]+)/runs/([^/]+)/approval-operations/([^/]+)")


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    decision: Literal["approve", "reject"]
    expected_revision: StrictInt = Field(ge=0, le=9007199254740991)
    operator: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1024)


class _Rollback(Exception):
    def __init__(self, response: ApiResponse):
        self.response = response


def _current(
    app: Any,
    request: Any,
    task: TaskId,
    run: str,
    segment: SessionId,
    write: bool,
    *,
    canonical: bool = True,
) -> Any:
    platform = app.client_platform
    if (
        platform is None
        or platform.client_sessions is None
        or platform.frontend_capabilities is None
    ):
        return ApiResponse(503, {"status": "approval_operations_unavailable"})
    auth = SessionBackedClientGrantAuthorizer(platform.client_sessions).authorize(
        request.headers,
        host_context=request.host_context,
        require_host_context=app.settings.deployment == "cloud",
        verified_host_grant=request.verified_host_grant,
    )
    if auth is None:
        return ApiResponse(401, {"status": "client_session_authorization_required"})
    denied = task_access_response(
        app,
        str(task),
        request.host_context,
        verified_host_grant=request.verified_host_grant,
        run_id=run,
        required_scope="agent.run",
    )
    if denied is not None:
        return denied
    if app.stores.tasks.task_id_for_session(segment) != task:
        return ApiResponse(404, {"status": "approval_scope_not_found"})
    binding = platform.client_sessions.get_run_binding(task, run, auth.client_session_id)
    session = platform.client_sessions.get_session(auth.client_session_id)
    if binding is None or session is None:
        return ApiResponse(403, {"status": "client_run_binding_required"})
    profile = platform.frontend_capabilities.get_profile_by_digest(
        session.grant.frontend_app_id, session.grant.profile_digest
    )
    if (
        profile is None
        or profile.lifecycle.value != "published"
        or binding.profile_digest != profile.profile_digest
    ):
        return ApiResponse(403, {"status": "client_profile_changed"})
    if request.host_context is not None:
        current = platform.frontend_capabilities.get_binding_for_host(
            request.host_context.host_app_id,
            request.host_context.namespace_id,
            session.grant.frontend_app_id,
        )
        if current is None or current.profile_digest != binding.profile_digest:
            return ApiResponse(403, {"status": "client_profile_changed"})
    if write:
        header = app.stores.tasks.read_task_header(task)
        latest = app.stores.tasks.read_latest_run_header(task) if canonical else None
        if (
            header is None
            or header.active_segment_id != segment
            or canonical
            and (latest is None or latest.run_id != run)
        ):
            return ApiResponse(409, {"status": "approval_target_changed"})
        headers = {k.lower(): v for k, v in (request.headers or {}).items()}
        lease = (
            platform.client_control_leases.get_active(binding.binding_id)
            if platform.client_control_leases
            else None
        )
        if lease is None or lease.is_expired() or lease.client_session_id != auth.client_session_id:
            return ApiResponse(409, {"status": "controller_required"})
        lease.require_controller()
        lease.require_fence(ClientControlFence(token=headers.get("x-zebra-client-fence", "")))
    return auth


def _receipt(event: Any, binding: dict[str, object]) -> ApiResponse:
    if event is None:
        return ApiResponse(200, {"status": "not_observed"})
    original = event.payload.get("client_approval_operation")
    if not isinstance(original, dict) or any(original.get(k) != v for k, v in binding.items()):
        return ApiResponse(409, {"status": "approval_operation_conflict"})
    return ApiResponse(
        200,
        {
            "status": "completed",
            "operation": original["operation"],
            "decision": original["decision"],
            "request_hash": original["request_hash"],
            "event_id": str(event.event_id),
            "sequence": event.sequence,
        },
    )


def handle_client_approval_operation(app: Any, request: Any) -> ApiResponse | None:
    if request.path.endswith("/client-authority"):
        return _authority(app, request)
    match = _ROUTE.fullmatch(request.path)
    if match is None:
        return None
    if request.method not in {"POST", "GET"}:
        return ApiResponse(405, {"status": "method_not_allowed"})
    write = request.method == "POST"
    try:
        task, run, operation = TaskId(UUID(match[1])), match[2], str(UUID(match[3]))
        if (
            operation != match[3]
            or not UUID(operation).int
            or not re.fullmatch(r"[\x21-\x7e]{1,128}", run)
        ):
            raise ValueError("invalid original identity")
        headers = {k.lower(): v for k, v in (request.headers or {}).items()}
        segment = SessionId(UUID(headers.get("x-zebra-command-segment", "")))
        if (
            request.query
            or not write
            and (
                request.body is not None
                or headers.get("content-length", "0") != "0"
                or "transfer-encoding" in headers
            )
        ):
            raise ValueError("receipt input rejected")
        decision = Decision.model_validate(request.body) if write else None
        if decision and (not decision.operator.strip() or not decision.reason.strip()):
            raise ValueError("blank decision")
    except (ValueError, TypeError):
        return ApiResponse(400, {"status": "invalid_approval_operation"})
    store = app.stores.events
    if not isinstance(store, ClientApprovalOperationPort):
        return ApiResponse(503, {"status": "approval_operations_unavailable"})
    key = "client-approval-v1:" + operation
    try:
        with task_io_deadline(monotonic() + 4):
            auth = _current(app, request, task, run, segment, write)
            if isinstance(auth, ApiResponse):
                return auth
            binding: dict[str, object] = {
                "version": 1,
                "task": str(task),
                "run": run,
                "segment": str(segment),
                "client": str(auth.client_session_id),
                "operation": operation,
            }
            if decision:
                raw = json.dumps(
                    {**binding, **decision.model_dump()},
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                binding.update(
                    decision=decision.decision,
                    request_hash=hashlib.sha256(raw.encode()).hexdigest(),
                )
            if not write:
                result = _receipt(store.read_approval_operation(segment, key), binding)
            else:
                with store.approval_operation_unit(segment):
                    current = _current(app, request, task, run, segment, True)
                    if isinstance(current, ApiResponse):
                        raise _Rollback(current)
                    event = store.read_approval_operation(segment, key)
                    if event is None:
                        assert decision is not None
                        _commit(app, segment, key, binding, decision)
                        event = store.read_approval_operation(segment, key)
                        if event is None:
                            raise RuntimeError("atomic approval receipt missing")
                    result = _receipt(event, binding)
            current = _current(app, request, task, run, segment, False)
            return current if isinstance(current, ApiResponse) else result
    except _Rollback as exc:
        return exc.response
    except ValueError:
        return ApiResponse(409, {"status": "approval_authority_changed"})
    except Exception:
        return ApiResponse(503, {"status": "approval_operation_unknown"})


def _commit(
    app: Any, segment: SessionId, key: str, binding: dict[str, object], decision: Decision
) -> None:
    # Only called inside the native stream lock/work unit. Never load historical event bodies.
    session = app.stores.sessions.get_session(segment)
    if session is None or session.current_sequence != decision.expected_revision:
        raise _Rollback(ApiResponse(409, {"status": "approval_revision_changed"}))
    event = ApprovalDecisionService().build_event(
        session=session,
        next_sequence=session.current_sequence + 1,
        command=ApprovalDecisionCommand(
            action=ApprovalDecisionAction.GRANT
            if decision.decision == "approve"
            else ApprovalDecisionAction.REJECT,
            operator=decision.operator,
            reason=decision.reason,
        ),
    )
    event = event.model_copy(
        update={
            "idempotency_key": key,
            "payload": {**event.payload, "client_approval_operation": binding},
        }
    )
    app.stores.events.append(event)
    app.stores.sessions.save_session(apply_event(session, event))
    workspace = app.stores.workspaces.get_workspace(segment)
    if workspace is not None:
        app.stores.workspaces.save_workspace(apply_workspace_event(workspace, event))
    if decision.decision == "approve":
        command = SessionCommand(
            command_id=uuid4(),
            session_id=segment,
            kind=SessionCommandKind.RESUME,
            expected_revision=event.sequence,
            idempotency_key=f"approval-resume:{segment}:{event.sequence}:resume",
            payload={},
        )
        app.stores.events.append(
            SessionEvent.create(
                session_id=segment,
                sequence=event.sequence + 1,
                event_type=EventType.SESSION_COMMAND_ACCEPTED,
                actor=EventActor.HARNESS,
                idempotency_key=command.idempotency_key,
                payload=command.event_payload(),
            )
        )


def _authority(app: Any, request: Any) -> ApiResponse | None:
    match = re.fullmatch(r"/v1/tasks/([^/]+)/runs/([^/]+)/client-authority", request.path)
    if match is None:
        return None
    if request.method != "GET":
        return ApiResponse(405, {"status": "method_not_allowed"})
    try:
        if request.body is not None or request.query:
            raise ValueError("body-free authority observation required")
        task, run = TaskId(UUID(match[1])), match[2]
        if not re.fullmatch(r"[\x21-\x7e]{1,128}", run):
            raise ValueError("bounded Run required")
        headers = {k.lower(): v for k, v in (request.headers or {}).items()}
        segment = SessionId(UUID(headers.get("x-zebra-command-segment", "")))
        with task_io_deadline(monotonic() + 3):
            auth = _current(app, request, task, run, segment, True, canonical=False)
            if isinstance(auth, ApiResponse):
                return auth
            session = app.client_platform.client_sessions.get_session(auth.client_session_id)
            return ApiResponse(
                200,
                {
                    "contract_version": 1,
                    "task_id": str(task),
                    "run_id": run,
                    "segment_id": str(segment),
                    "client_session_id": str(auth.client_session_id),
                    "profile_digest": session.grant.profile_digest,
                    "controller": True,
                },
            )
    except ValueError:
        return ApiResponse(409, {"status": "client_authority_changed"})
    except Exception:
        return ApiResponse(503, {"status": "client_authority_unavailable"})
