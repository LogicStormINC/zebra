"""Revision-two complete input responses at the existing native authority boundary."""

# Native operation identity and all authority coordinates remain BFF-owned.
import hashlib
import json
import re
from dataclasses import replace
from time import monotonic
from typing import Any
from uuid import UUID

from ag_ui.core import ResumeEntry, RunAgentInput
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.client_effects import RECEIPT_TERMINAL_STATUSES, ClientEffectReceipt
from agent_core.domain.client_preparation import ClientPreparationContext
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.client_approval_operations import ClientApprovalOperationPort
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_integrations.ag_ui.profiles import AgUiProfileRegistry
from agent_storage.postgres.task_io import task_io_deadline
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from zebra_agent_api.ag_ui_client_state import bound_client_state_profile
from zebra_agent_api.ag_ui_command_receipts import native_interaction_receipt
from zebra_agent_api.ag_ui_public_binding import standard_state_after
from zebra_agent_api.client_approval_operations import Decision, _commit, _current, _Rollback
from zebra_agent_api.client_effect_receipts import submit_client_effect_receipt
from zebra_agent_api.responses import ApiResponse


def validate_response_set(
    value: RunAgentInput, public_run_id: str, pending_ids: list[str]
) -> tuple[ResumeEntry, ...]:
    """Validate the entire exact latest set before dispatching any native decision."""
    json.dumps(value.model_dump(mode="python", by_alias=True), allow_nan=False)
    entries = tuple(value.resume or ())
    ids = [entry.interrupt_id for entry in entries]
    if (
        value.protocol_version not in {None, "1.0"}
        or value.run_id != public_run_id
        or not pending_ids
        or len(ids) != len(set(ids))
        or set(ids) != set(pending_ids)
        or any(entry.model_extra or entry.metadata is not None for entry in entries)
    ):
        raise ValueError("response must cover exactly the latest interrupted protocol run")
    return entries


_ROUTE = re.compile(r"/agui/threads/([^/]+)/runs/([^/]+)/interaction")


class InteractionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: StrictInt = Field(alias="expectedRevision", ge=0)
    input: RunAgentInput
    previous_native_run_id: str | None = Field(
        default=None, alias="previousNativeRunId", max_length=128
    )
    receipt: ClientEffectReceipt | None = None


def _error(status: str, code: int = 409) -> ApiResponse:
    return ApiResponse(code, {"status": status})


def _current_input(
    app: Any,
    request: Any,
    body: InteractionInput,
    task: TaskId,
    run: str,
    segment: SessionId,
    profile: Any,
) -> tuple[Any, Any]:
    prior = body.previous_native_run_id or run
    authority = _current(app, request, task, run, segment, True, canonical=prior == run)
    if isinstance(authority, ApiResponse):
        raise _Rollback(authority)
    if prior != run:
        previous = request.previous_verified_host_grant
        current = request.verified_host_grant
        if (
            previous is None
            or current is None
            or request.previous_host_context != previous.context
            or previous.grant_id == current.grant_id
            or previous.subject_ref != current.subject_ref
            or previous.authority_issuer != current.authority_issuer
            or any(
                getattr(previous.context, field) != getattr(current.context, field)
                for field in ("host_app_id", "namespace_id", "workspace_ref", "origin")
            )
        ):
            raise ValueError("separate current authority for the old pending Run is required")
        old_request = replace(
            request, host_context=request.previous_host_context, verified_host_grant=previous
        )
        old = _current(app, old_request, task, prior, segment, False)
        if isinstance(old, ApiResponse):
            raise _Rollback(old)
        latest = app.stores.tasks.read_latest_run_header(task)
        if latest is None or latest.run_id != prior:
            raise ValueError("pending native Run changed")
    # Public state and tools in a response are observations, never new mounts.
    if not isinstance(body.input.forwarded_props, dict):
        raise ValueError("current native Surface metadata is required")
    denied = bound_client_state_profile(
        app,
        request,
        {
            "thread_id": str(task),
            "run_id": run,
            "input": {"state": {}, "tools": []},
        },
        body.input.forwarded_props,
    )
    if isinstance(denied, ApiResponse):
        raise _Rollback(denied)
    session = app.stores.sessions.get_session(segment)
    if session is None or session.current_sequence != body.expected_revision:
        raise ValueError("native revision changed")
    native = app.stores.tasks.read_run_header(task, prior)
    if native.strict_coverage:
        raise _Rollback(_error("native_interaction_unsupported_privacy"))
    source = app.stores.tasks.read_event_header(task, native.highwater)
    if source is None:
        raise CheckpointNotReady("native source is not indexed")
    from agent_core.ports.task_projection_checkpoints import ProjectionScope

    scope = ProjectionScope(
        getattr(app.stores, "deployment_namespace", None) or "local",
        task,
        native.anchor.event_id,
        profile.checkpoint_version(coverage=native.strict_coverage),
    )
    state = standard_state_after(app.stores.tasks, scope, native, source, profile)
    if (
        body.input.thread_id != str(task)
        or not state.turn_finished
        or body.input.run_id != state.protocol_run_id
    ):
        raise ValueError("response does not target the latest closed public run")
    return session, state


def _effect_input(
    app: Any,
    body: InteractionInput,
    state: Any,
    task: TaskId,
    run: str,
    segment: SessionId,
    operation: UUID,
    effect_id: UUID,
    auth: Any,
) -> None:
    receipt = body.receipt
    effect = app.client_platform.client_effects.get_effect(effect_id)
    pending = state.pending_effects
    if (
        receipt is None
        or body.input.resume is not None
        or len(pending) != 1
        or str(effect_id) not in pending
        or effect is None
        or receipt.effect_id != effect_id
        or receipt.receipt_id != operation
        or effect.task_id != task
        or effect.run_id != run
        or effect.parent_session_id != segment
        or effect.client_session_id != auth.client_session_id
        or receipt.request_digest != effect.request_digest
        or not receipt.matches(effect)
        or receipt.status not in RECEIPT_TERMINAL_STATUSES
    ):
        raise ValueError("response does not match the exact pending native effect")
    descriptor = pending[str(effect_id)]
    call = str(effect.tool_call_id)
    if (
        descriptor.get("request_digest") != receipt.request_digest
        or descriptor.get("tool_call_id") != call
        or set(state.pending_tools) != {call}
    ):
        raise ValueError("unsupported pending frontend result combination")
    tools = [message for message in body.input.messages if message.role == "tool"]
    if len(tools) != 1 or tools[0].tool_call_id != call or tools[0].id != "tool-result:" + call:
        raise ValueError("all pending frontend results need their canonical tool message")
    if not isinstance(tools[0].content, str):
        raise ValueError("frontend result content must be canonical JSON text")
    content = json.loads(tools[0].content)
    from zebra_agent_api.ag_ui_standard_http import _same_json

    if not _same_json(content, {"status": receipt.status.value, "result": receipt.result}):
        raise ValueError("tool result differs from the original native receipt")


def _cancel_clarification(
    app: Any,
    request: Any,
    body: InteractionInput,
    task: TaskId,
    run: str,
    segment: SessionId,
    profile: Any,
    context: ClientPreparationContext,
) -> None:
    if app.cloud_control is None or request.host_context is None or body.previous_native_run_id:
        raise ValueError("native clarification cancellation requires its original cloud target")

    def authorize() -> None:
        session, state = _current_input(app, request, body, task, run, segment, profile)
        entries = validate_response_set(
            body.input, state.protocol_run_id, state.public_execution.get("openInterruptIds", [])
        )
        clarification = session.clarification_context
        if (
            len(entries) != 1
            or entries[0].status != "cancelled"
            or session.status is not SessionStatus.WAITING_INPUT
            or clarification is None
            or entries[0].interrupt_id != "clarification:" + clarification.clarification_id
            or entries[0].payload is not None
            or body.receipt is not None
        ):
            raise ValueError("native clarification cancellation conflicts")

    # Observe before native derived read-state preparation; the same check runs
    # again after the native cancellation locks, in its own exact transaction.
    authorize()
    scope = app.cloud_control.host_scope(segment, request.host_context)
    app.cloud_control.cancel(
        segment,
        scope=scope,
        workspace_ref=request.host_context.workspace_ref,
        host_context=request.host_context,
        task_id=task,
        operation_id=context.operation_id,
        preparation=context,
        authorize_preparation=authorize,
    )


def handle_native_interaction(app: Any, request: Any) -> ApiResponse | None:
    match = _ROUTE.fullmatch(request.path)
    if match is None:
        return None
    if request.method not in {"POST", "GET"}:
        return _error("method_not_allowed", 405)
    try:
        headers = {k.lower(): v for k, v in (request.headers or {}).items()}
        profile = (app.agui_profiles or AgUiProfileRegistry()).select(
            headers.get("x-zebra-agui-profile"), headers.get("x-zebra-agui-revision")
        )
        if profile is None or profile.revision != 2:
            raise ValueError("explicit interaction revision required")
        task, run = TaskId(UUID(match[1])), match[2]
        operation = UUID(headers.get("idempotency-key", ""))
        segment = SessionId(UUID(headers.get("x-zebra-command-segment", "")))
        effect = UUID(headers["x-zebra-effect-id"]) if "x-zebra-effect-id" in headers else None
        if (
            str(operation) != headers["idempotency-key"]
            or not operation.int
            or not re.fullmatch(r"[\x21-\x7e]{1,128}", run)
            or request.query
        ):
            raise ValueError("invalid original operation")
        write = request.method == "POST"
        if not write and (
            request.body is not None
            or headers.get("content-length", "0") != "0"
            or "transfer-encoding" in headers
        ):
            raise ValueError("original receipt observation is body-free")
        body = InteractionInput.model_validate(request.body) if write else None
        if body is not None:
            raw = json.dumps(request.body, sort_keys=True, separators=(",", ":"), allow_nan=False)
            request_hash = hashlib.sha256(raw.encode()).hexdigest()
        else:
            request_hash = None
        with task_io_deadline(monotonic() + 4):
            auth = _current(app, request, task, run, segment, False)
            if isinstance(auth, ApiResponse):
                return auth
            original = native_interaction_receipt(
                app, request, profile, task, run, segment, operation, effect, auth, request_hash
            )
            if original is not None:
                return original
            if not write:
                return _error("not_observed", 200)
            if not isinstance(app.stores.events, ClientApprovalOperationPort):
                return _error("native_interaction_unavailable", 503)
            assert body is not None and request_hash is not None
            privacy = app.stores.tasks.read_run_header(
                task, body.previous_native_run_id or run
            ).strict_coverage
            if privacy:
                return _error("native_interaction_unsupported_privacy")
            context = ClientPreparationContext(
                operation_id=operation,
                client_session_id=auth.client_session_id,
                task_id=task,
                run_id=run,
                request_hash=request_hash,
                projection_version=profile.checkpoint_version(coverage=privacy),
                input=body.input.model_dump(mode="json", by_alias=True, exclude_none=True),
                previous_run_id=body.input.run_id,
            )
            # The existing native payload budget applies to terminal responses too.
            SessionCommand(
                session_id=segment,
                kind=SessionCommandKind.RESUME,
                expected_revision=body.expected_revision,
                idempotency_key=str(operation),
                payload={
                    "input": context.input,
                    "client_preparation": context.model_dump(mode="json", exclude={"input"}),
                },
            )
            cancellation = (
                effect is None
                and body.input.resume
                and any(
                    entry.status == "cancelled" and entry.interrupt_id.startswith("clarification:")
                    for entry in body.input.resume
                )
            )
            if cancellation:
                _cancel_clarification(app, request, body, task, run, segment, profile, context)
                return native_interaction_receipt(
                    app, request, profile, task, run, segment, operation, effect, auth, request_hash
                ) or _error("binding_pending", 202)
            with app.stores.events.approval_operation_unit(segment):
                session, state = _current_input(app, request, body, task, run, segment, profile)
                if effect is not None:
                    if (
                        session.status
                        not in {SessionStatus.RUNNING, SessionStatus.WAITING_CLIENT_EFFECT}
                        or state.public_execution.get("status") != "waiting_client_effect"
                    ):
                        raise ValueError("native effect is no longer pending")
                    _effect_input(app, body, state, task, run, segment, operation, effect, auth)
                    assert body.receipt is not None
                    result = submit_client_effect_receipt(
                        app,
                        str(effect),
                        body.receipt.model_dump(
                            mode="json", exclude={"effect_id", "idempotency_key"}
                        ),
                        client_session_id=auth.client_session_id,
                        fence_token=headers.get("x-zebra-client-fence", ""),
                        controller=True,
                        idempotency_key=body.receipt.idempotency_key,
                        host_context=request.host_context,
                        verified_host_grant=request.verified_host_grant,
                        preparation=context,
                    )
                    if result.status_code != 200 or result.body.get("status") not in {
                        status.value for status in RECEIPT_TERMINAL_STATUSES
                    }:
                        raise _Rollback(result)
                else:
                    entries = validate_response_set(
                        body.input,
                        state.protocol_run_id,
                        state.public_execution.get("openInterruptIds", []),
                    )
                    if len(entries) != 1 or body.receipt is not None:
                        raise ValueError("native pending aggregate is singleton")
                    entry = entries[0]
                    if session.status is SessionStatus.WAITING_APPROVAL:
                        expected = session.approval_context
                        if expected is None or (
                            expected.tool_call_id is not None
                            and entry.interrupt_id != "approval:" + expected.tool_call_id
                        ):
                            raise ValueError("native approval identity changed")
                        payload = entry.payload
                        if not isinstance(payload, dict):
                            raise ValueError("approval requires an explicit decision payload")
                        if (
                            entry.status == "cancelled"
                            and payload.get("decision", "reject") != "reject"
                        ):
                            raise ValueError("cancelled approval conflicts with a grant decision")
                        decision = Decision.model_validate(
                            {
                                **payload,
                                "expected_revision": body.expected_revision,
                                **({"decision": "reject"} if entry.status == "cancelled" else {}),
                            }
                        )
                        _commit(
                            app,
                            segment,
                            f"agui-interaction:{operation}",
                            {
                                "version": 2,
                                "operation": str(operation),
                                "request_hash": request_hash,
                                "client": str(auth.client_session_id),
                            },
                            decision,
                            context,
                        )
                    elif (
                        session.status is SessionStatus.WAITING_INPUT and entry.status == "resolved"
                    ):
                        clarification = session.clarification_context
                        if (
                            body.previous_native_run_id is None
                            or body.previous_native_run_id == run
                            or clarification is None
                            or entry.interrupt_id
                            != "clarification:" + clarification.clarification_id
                            or not isinstance(entry.payload, dict)
                            or set(entry.payload) != {"content"}
                            or not isinstance(entry.payload["content"], str)
                            or not entry.payload["content"].strip()
                            or clarification.response_schema is not None
                        ):
                            raise ValueError("unsupported native clarification response")
                        command_payload = {
                            "run_id": run,
                            "content": entry.payload["content"],
                            "clarification_id": clarification.clarification_id,
                            "input": context.input,
                        }
                        SessionCommand(
                            session_id=segment,
                            kind=SessionCommandKind.MESSAGE,
                            expected_revision=body.expected_revision,
                            idempotency_key=f"agui-interaction:{operation}",
                            payload=command_payload,
                        )
                        result = app.submit_command(
                            str(segment),
                            {
                                "kind": "message",
                                "expected_revision": body.expected_revision,
                                "payload": command_payload,
                            },
                            idempotency_key=f"agui-interaction:{operation}",
                            verified_host_grant=request.verified_host_grant,
                            native_preparation=context,
                        )
                        if result.status_code not in {200, 202}:
                            raise _Rollback(result)
                    else:
                        raise ValueError("native pending response is unavailable")
            current = _current(app, request, task, run, segment, False)
            if isinstance(current, ApiResponse):
                return current
            return native_interaction_receipt(
                app, request, profile, task, run, segment, operation, effect, auth, request_hash
            ) or _error("binding_pending", 202)
    except _Rollback as exc:
        return exc.response
    except CheckpointNotReady:
        return _error("binding_pending", 202)
    except PermissionError:
        return _error("agui_input_scope_denied", 403)
    except (ValueError, TypeError, KeyError, AttributeError):
        return _error("native_interaction_conflict")
