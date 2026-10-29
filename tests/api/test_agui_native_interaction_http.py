"""Real native producer, receipts and continuations; signed HTTP consumer gate follows."""

import json
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.application.mock_model import ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tools import ToolCall

from tests.agent_storage.test_postgres_projection_source_metadata import (
    metadata_dsn as _metadata_dsn,
)
from tests.api.agui_native_interaction_fixture import (
    native_fixture,
    official_http_gate,
    public_state,
)
from tests.integration.test_client_effect_suspend_resume import _completion
from tests.worker.execution.worker_execution_support import _final_response

metadata_dsn = _metadata_dsn


def completion(tool):
    value = _completion(tool)
    from dataclasses import replace

    return replace(
        value, assistant_message=value.assistant_message.model_copy(update={"tool_calls": (tool,)})
    )


def call(name, arguments):
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime.now(UTC),
    )


def input_value(task, state, forwarded, **extra):
    return {
        "threadId": str(task),
        "runId": state.protocol_run_id,
        "protocolVersion": "1.0",
        "state": {},
        "messages": [],
        "tools": [],
        "context": [],
        "forwardedProps": forwarded,
        **extra,
    }


@pytest.mark.parametrize("profile_id", ["agui-standard-1.0", "zebra-reliable-v2-agui-1.0"])
def test_three_sequential_native_effects_capture_one_original_receipt_and_resume_each(
    metadata_dsn,
    tmp_path,
    monkeypatch,
    profile_id,
):
    calls = [call("app.ui.item.open", {"itemId": str(i)}) for i in range(3)]
    responses = [ScriptedModelResponse(completion=completion(value)) for value in calls]
    from agent_core.domain.client_capabilities import ClientActionContract

    from tests.api.test_client_runtime_api import _profile

    frontend_profile = _profile()
    action = ClientActionContract.model_validate(
        {
            **frontend_profile.actions[0].model_dump(),
            "max_result_bytes": 64,
            "result_schema": {
                "type": "object",
                "properties": {"opened": {"type": "integer", "minimum": 0, "maximum": 2}},
                "required": ["opened"],
                "additionalProperties": False,
            },
        }
    )
    frontend_profile = frontend_profile.model_copy(update={"actions": (action,)})
    fixture = native_fixture(
        metadata_dsn,
        tmp_path,
        monkeypatch,
        [*responses, _final_response("Three browser actions are resolved.")],
        profile_id=profile_id,
        frontend_profile=frontend_profile,
    )
    app, task, run, initial, original, headers, forwarded, gateway, consumer, request = fixture
    assert (
        consumer().consume_once(worker_id="g5a-effect-initial", lease_ttl_seconds=30).status
        == "executed"
    )
    locators = []
    for index, tool in enumerate(calls):
        state = public_state(app, task, run, profile_id)
        assert state.public_execution == {"status": "waiting_client_effect"}, [
            (e.event_type.value, e.payload)
            for e in app.stores.events.list_for_session(task)
            if e.event_type in {EventType.SESSION_FAILED, EventType.TURN_FAILED}
        ]
        effect = app.client_platform.client_effects.list_pending(
            app.client_platform.client_sessions.get_active_run_binding(task).client_session_id
        )[0]
        assert set(state.pending_tools) == {str(tool.tool_call_id)}, (
            state.pending_tools,
            [
                (e.event_type.value, e.payload.get("tool_call_id"))
                for e in app.stores.events.list_for_session(task)
                if "tool" in e.event_type.value
            ],
        )
        operation = uuid4()
        result = {"opened": index}
        status = ("succeeded", "declined", "failed")[index]
        receipt = {
            "receipt_id": str(operation),
            "effect_id": str(effect.effect_id),
            "idempotency_key": effect.idempotency_key,
            "request_digest": effect.request_digest,
            "status": status,
            "result": result,
            "controller": True,
            "received_at": datetime.now(UTC).isoformat(),
        }
        body = {
            "expectedRevision": app.stores.sessions.get_session(task).current_sequence,
            "receipt": receipt,
            "input": input_value(
                task,
                state,
                forwarded,
                messages=[
                    {
                        "id": "tool-result:" + str(tool.tool_call_id),
                        "role": "tool",
                        "toolCallId": str(tool.tool_call_id),
                        "content": json.dumps({"status": status, "result": result}),
                    }
                ],
            ),
        }
        extra = {"X-Zebra-Effect-Id": str(effect.effect_id)}
        before = app.stores.events.list_for_session(task)
        wrong = {**body, "receipt": {**receipt, "request_digest": "f" * 64}}
        assert (
            request("POST", "interaction", body=wrong, operation=operation, extra=extra).status_code
            == 409
        )
        assert app.stores.events.list_for_session(task) == before
        if index == 0:
            from copy import deepcopy

            invalid = deepcopy(body)
            invalid["receipt"]["result"] = {"opened": "invalid"}
            invalid["input"]["messages"][0]["content"] = json.dumps(
                {"status": "succeeded", "result": {"opened": "invalid"}}
            )
            invalid_op = uuid4()
            invalid["receipt"]["receipt_id"] = str(invalid_op)
            rejected = request(
                "POST", "interaction", body=invalid, operation=invalid_op, extra=extra
            )
            assert rejected.status_code == 422, rejected.body
            assert app.stores.events.list_for_session(task) == before
        accepted = request("POST", "interaction", body=body, operation=operation, extra=extra)
        assert accepted.status_code == 202, (index, accepted.body)
        events = app.stores.events.list_for_session(task)
        assert (
            len([e for e in events if e.event_type is EventType.CLIENT_EFFECT_RECEIPT_ACCEPTED])
            == index + 1
        )
        assert (
            len([e for e in events if e.event_type is EventType.SESSION_COMMAND_ACCEPTED])
            == index + 2
        )
        assert (
            consumer()
            .consume_once(worker_id=f"g5a-effect-resume-{index}", lease_ttl_seconds=30)
            .status
            == "executed"
        )
        public_state(app, task, run, profile_id)
        before_read = app.stores.events.list_for_session(task)
        prepared = request("GET", "interaction", operation=operation, extra=extra)
        assert prepared.status_code == 200 and prepared.body["status"] == "prepared", prepared.body
        assert (
            request(
                "GET",
                "interaction",
                operation=operation,
                extra={**extra, "X-Zebra-Client-Fence": "old"},
            ).body
            == prepared.body
        )
        assert (
            request("POST", "interaction", body=body, operation=operation, extra=extra).body
            == prepared.body
        )
        assert app.stores.events.list_for_session(task) == before_read
        locators.append(
            {
                "operation": str(operation),
                "effectId": str(effect.effect_id),
                "toolCallId": str(tool.tool_call_id),
                "status": status,
                "result": result,
            }
        )
    before_http = app.stores.events.list_for_session(task)
    official_http_gate(app, initial, headers, locators, metadata_dsn, tmp_path, monkeypatch)
    assert app.stores.events.list_for_session(task) == before_http
    assert len(gateway.requests) == 4
    assert app.stores.sessions.get_session(task).status is SessionStatus.AWAITING_TURN
    assert (
        consumer().consume_once(worker_id="g5a-effect-idle", lease_ttl_seconds=30).status == "idle"
    )
    assert (
        len(
            app.client_platform.client_effects.list_pending(
                app.client_platform.client_sessions.get_active_run_binding(task).client_session_id
            )
        )
        == 0
    )


def test_three_sequential_native_approvals_use_actual_single_continuations(
    metadata_dsn,
    tmp_path,
    monkeypatch,
):
    calls = [
        call("command.run", {"command": [sys.executable, "-c", f"print('approved-{i}')"]})
        for i in range(3)
    ]
    fixture = native_fixture(
        metadata_dsn,
        tmp_path,
        monkeypatch,
        [
            *[ScriptedModelResponse(completion=completion(value)) for value in calls],
            _final_response("Three approvals are complete."),
        ],
    )
    app, task, run, initial, original, headers, forwarded, gateway, consumer, request = fixture
    assert (
        consumer().consume_once(worker_id="g5a-approval-initial", lease_ttl_seconds=30).status
        == "executed"
    )
    for index, tool in enumerate(calls):
        assert app.stores.sessions.get_session(task).status is SessionStatus.WAITING_APPROVAL, [
            (e.event_type.value, e.payload)
            for e in app.stores.events.list_for_session(task)
            if e.event_type in {EventType.SESSION_FAILED, EventType.TURN_FAILED}
        ]
        state = public_state(app, task, run)
        response = {
            "interruptId": "approval:" + str(tool.tool_call_id),
            "status": "resolved",
            "payload": {
                "decision": "approve",
                "operator": "fixture-user",
                "reason": "approved exact native tool",
            },
        }
        body = {
            "expectedRevision": app.stores.sessions.get_session(task).current_sequence,
            "input": input_value(task, state, forwarded, resume=[response]),
        }
        operation = uuid4()
        before = app.stores.events.list_for_session(task)
        malformed = {**body, "input": {**body["input"], "resume": [response, response]}}
        assert (
            request("POST", "interaction", body=malformed, operation=operation).status_code == 409
        )
        assert app.stores.events.list_for_session(task) == before
        if index == 0:
            from copy import deepcopy

            variants = []
            for entries in ([], [{**response, "interruptId": "approval:unknown"}]):
                invalid = deepcopy(body)
                invalid["input"]["resume"] = entries
                variants.append(invalid)
            for field, value in (
                ("runId", "agui:" + "f" * 64),
                ("forwardedProps", {**forwarded, "uiRevision": 99}),
            ):
                invalid = deepcopy(body)
                invalid["input"][field] = value
                variants.append(invalid)
            large = deepcopy(body)
            large["input"]["messages"] = [
                {"id": "bounded-native-input", "role": "user", "content": "x" * 65536}
            ]
            variants.append(large)
            for invalid in variants:
                rejected = request("POST", "interaction", body=invalid, operation=uuid4())
                assert rejected.status_code in {400, 403, 409, 422}, rejected.body
                assert app.stores.events.list_for_session(task) == before
            unknown = request("GET", "interaction", operation=uuid4())
            assert unknown.body["status"] == "not_observed"
            stale = request(
                "POST",
                "interaction",
                body=body,
                operation=uuid4(),
                extra={"X-Zebra-Client-Fence": "stale"},
            )
            assert stale.status_code == 409, stale.body
            assert app.stores.events.list_for_session(task) == before
        accepted = request("POST", "interaction", body=body, operation=operation)
        assert accepted.status_code == 202, (index, accepted.body)
        assert (
            consumer()
            .consume_once(worker_id=f"g5a-approval-resume-{index}", lease_ttl_seconds=30)
            .status
            == "executed"
        )
        public_state(app, task, run)
        prepared = request("GET", "interaction", operation=operation)
        assert prepared.status_code == 200 and prepared.body["status"] == "prepared", prepared.body
        events = app.stores.events.list_for_session(task)
        assert len([e for e in events if e.event_type is EventType.APPROVAL_GRANTED]) == index + 1
        assert (
            len([e for e in events if e.event_type is EventType.SESSION_COMMAND_ACCEPTED])
            == index + 2
        )
    assert len(gateway.requests) == 4
    assert app.stores.sessions.get_session(task).status is SessionStatus.AWAITING_TURN


@pytest.mark.parametrize("response_status", ["resolved", "cancelled"])
def test_native_rejection_is_terminal_acknowledgement_without_worker_or_model(
    metadata_dsn,
    tmp_path,
    monkeypatch,
    response_status,
):
    tool = call("command.run", {"command": [sys.executable, "-c", "print('never-executed')"]})
    fixture = native_fixture(
        metadata_dsn, tmp_path, monkeypatch, [ScriptedModelResponse(completion=completion(tool))]
    )
    app, task, run, initial, original, headers, forwarded, gateway, consumer, request = fixture
    assert (
        consumer().consume_once(worker_id="g5a-reject", lease_ttl_seconds=30).status == "executed"
    )
    state = public_state(app, task, run)
    operation = uuid4()
    body = {
        "expectedRevision": app.stores.sessions.get_session(task).current_sequence,
        "input": input_value(
            task,
            state,
            forwarded,
            resume=[
                {
                    "interruptId": "approval:" + str(tool.tool_call_id),
                    "status": response_status,
                    "payload": {
                        "decision": "reject",
                        "operator": "fixture-user",
                        "reason": "explicit original rejection",
                    },
                }
            ],
        ),
    }
    before = app.stores.events.list_for_session(task)
    assert request("POST", "interaction", body=body, operation=operation).status_code == 202
    assert app.stores.sessions.get_session(task).status is SessionStatus.FAILED
    public_state(app, task, run)
    prepared = request("GET", "interaction", operation=operation)
    assert prepared.status_code == 200 and prepared.body["status"] == "prepared", prepared.body
    assert prepared.body["previousRunId"] == state.protocol_run_id
    events = app.stores.events.list_for_session(task)
    assert len(events) == len(before) + 1
    assert events[-1].event_type is EventType.APPROVAL_REJECTED
    assert events[-1].payload["input"]["resume"][0]["status"] == response_status
    assert len([e for e in events if e.event_type is EventType.SESSION_COMMAND_ACCEPTED]) == 1
    assert len(gateway.requests) == 1
    assert (
        consumer().consume_once(worker_id="g5a-reject-idle", lease_ttl_seconds=30).status == "idle"
    )
    assert (
        request(
            "GET", "interaction", operation=operation, extra={"X-Zebra-Client-Fence": "stale"}
        ).body
        == prepared.body
    )


def test_clarification_cancel_uses_actual_native_direct_cancel_and_no_continuation(
    metadata_dsn,
    tmp_path,
    monkeypatch,
):
    tool = call("agent.clarify", {"question": "Choose a scope", "choices": ["One", "All"]})
    fixture = native_fixture(
        metadata_dsn, tmp_path, monkeypatch, [ScriptedModelResponse(completion=completion(tool))]
    )
    app, task, run, initial, original, headers, forwarded, gateway, consumer, request = fixture
    assert (
        consumer().consume_once(worker_id="g5a-clarify-cancel", lease_ttl_seconds=30).status
        == "executed"
    )
    assert app.stores.sessions.get_session(task).status is SessionStatus.WAITING_INPUT
    state = public_state(app, task, run)
    operation = uuid4()
    body = {
        "expectedRevision": app.stores.sessions.get_session(task).current_sequence,
        "input": input_value(
            task,
            state,
            forwarded,
            resume=[
                {"interruptId": "clarification:" + str(tool.tool_call_id), "status": "cancelled"}
            ],
        ),
    }
    before = app.stores.events.list_for_session(task)
    assert (
        request(
            "POST",
            "interaction",
            body=body,
            operation=operation,
            extra={"X-Zebra-Client-Fence": "old"},
        ).status_code
        == 409
    )
    assert app.stores.events.list_for_session(task) == before
    accepted = request("POST", "interaction", body=body, operation=operation)
    assert accepted.status_code == 202, accepted.body
    assert app.stores.sessions.get_session(task).status is SessionStatus.CANCELLED
    public_state(app, task, run)
    prepared = request("GET", "interaction", operation=operation)
    assert prepared.status_code == 200 and prepared.body["status"] == "prepared", prepared.body
    assert prepared.body["previousRunId"] == state.protocol_run_id
    events = app.stores.events.list_for_session(task)
    assert len([e for e in events if e.event_type is EventType.SESSION_CANCELLED]) == 1
    assert len([e for e in events if e.event_type is EventType.SESSION_COMMAND_ACCEPTED]) == 1
    assert len(gateway.requests) == 1
    assert (
        consumer().consume_once(worker_id="g5a-cancel-idle", lease_ttl_seconds=30).status == "idle"
    )
    assert (
        request(
            "GET", "interaction", operation=operation, extra={"X-Zebra-Client-Fence": "old"}
        ).body
        == prepared.body
    )


def test_native_clarification_answer_opens_authorized_new_run_on_the_same_task_and_segment(
    metadata_dsn,
    tmp_path,
    monkeypatch,
):
    from dataclasses import replace

    from agent_core.domain.host_authority import HostResourceRef
    from zebra_agent_api.routes import RouteAdapter, RouteRequest

    tool = call("agent.clarify", {"question": "Choose a scope", "choices": ["One", "All"]})
    fixture = native_fixture(
        metadata_dsn,
        tmp_path,
        monkeypatch,
        [ScriptedModelResponse(completion=completion(tool)), _final_response("Scope clarified.")],
    )
    app, task, run, initial, original, headers, forwarded, gateway, consumer, request = fixture
    assert (
        consumer().consume_once(worker_id="g5a-clarify", lease_ttl_seconds=30).status == "executed"
    )
    state = public_state(app, task, run)
    new_run = str(uuid4())
    context = initial.host_context.model_copy(
        update={
            "grant_id": str(uuid4()),
            "resource_refs": tuple(
                HostResourceRef(type="run", id=new_run) if ref.resource_type == "run" else ref
                for ref in initial.host_context.resource_refs
            ),
        }
    )
    verified = replace(initial.verified_host_grant, context=context, grant_id=context.grant_id)
    mount = {
        **initial.body["payload"]["surface"]["mount"],
        "client_session_id": forwarded["clientSessionId"],
        "ui_revision": 3,
        "mounted_actions": ["app.ui.item.open"],
        "mounted_at": datetime.now(UTC).isoformat(),
    }
    mounted = RouteAdapter(app).handle(
        RouteRequest(
            "POST",
            f"/v1/tasks/{task}/runs/{new_run}/client-surface",
            headers=headers,
            body={
                "mount": mount,
                "task_capability_scope": ["app.ui.item.open"],
                "controller": True,
            },
            host_context=context,
            verified_host_grant=verified,
        )
    )
    assert mounted.status_code == 201, mounted.body
    new_headers = {
        **headers,
        "X-Zebra-Client-Fence": mounted.body["controller_fence_token"],
        "Idempotency-Key": str(uuid4()),
    }
    new_forwarded = {
        **forwarded,
        "uiRevision": 3,
        "mountedSnapshotDigest": mounted.body["mounted_snapshot_digest"],
        "clientBindingDigest": mounted.body["binding_digest"],
    }
    body = {
        "expectedRevision": app.stores.sessions.get_session(task).current_sequence,
        "previousNativeRunId": run,
        "input": input_value(
            task,
            state,
            new_forwarded,
            resume=[
                {
                    "interruptId": "clarification:" + str(tool.tool_call_id),
                    "status": "resolved",
                    "payload": {"content": "all"},
                }
            ],
        ),
    }
    target = f"/agui/threads/{task}/runs/{new_run}/interaction"
    from tests.api.agui_native_interaction_fixture import signed_test_client

    http, signed = signed_test_client(app, initial, metadata_dsn, tmp_path, monkeypatch)
    before = app.stores.events.list_for_session(task)
    cases = [
        None,
        "Bearer unknown",
        signed(str(uuid4()))["Authorization"],
        signed(run, sub="another-user")["Authorization"],
        signed(run, namespace_id="another-namespace")["Authorization"],
        signed(run, exp=int(datetime.now(UTC).timestamp()) - 600)["Authorization"],
        signed(
            run,
            resource_refs=[
                {
                    "type": r.resource_type,
                    "id": "wrong-thread" if r.resource_type == "thread" else r.resource_id,
                }
                for r in initial.host_context.resource_refs
            ],
        )["Authorization"],
        signed(
            run,
            resource_refs=[
                *[
                    {"type": r.resource_type, "id": r.resource_id}
                    for r in initial.host_context.resource_refs
                ],
                {"type": "run", "id": new_run},
            ],
        )["Authorization"],
    ]
    for prior in cases:
        denied = http.post(
            target,
            json=body,
            headers={
                **new_headers,
                **signed(new_run),
                **({"X-Zebra-Previous-Host-Grant": prior} if prior is not None else {}),
            },
        )
        assert denied.status_code in {400, 401, 403, 404}, denied.text
        assert app.stores.events.list_for_session(task) == before
    same = signed(new_run)
    denied = http.post(
        target,
        json=body,
        headers={**new_headers, **same, "X-Zebra-Previous-Host-Grant": same["Authorization"]},
    )
    assert denied.status_code in {403, 404}, denied.text
    prior = signed(run)["Authorization"]
    denied = http.post(
        target,
        json=body,
        headers={
            **new_headers,
            **signed(new_run),
            "X-Zebra-Client-Fence": "old",
            "X-Zebra-Previous-Host-Grant": prior,
        },
    )
    assert denied.status_code == 409, denied.text
    replay = http.post(
        target,
        json=body,
        headers={**new_headers, **signed(new_run), "X-Zebra-Previous-Host-Grant": prior},
    )
    assert replay.status_code == 403, replay.text
    assert app.stores.events.list_for_session(task) == before
    response = http.post(
        target,
        json=body,
        headers={
            **new_headers,
            **signed(new_run),
            "X-Zebra-Previous-Host-Grant": signed(run)["Authorization"],
        },
    )
    assert response.status_code == 202, response.text
    assert (
        consumer().consume_once(worker_id="g5a-clarify-answer", lease_ttl_seconds=30).status
        == "executed"
    )
    public_state(app, task, new_run)
    receipt_http = http.get(
        target, headers={**new_headers, **signed(new_run), "X-Zebra-Client-Fence": "old"}
    )
    assert receipt_http.status_code == 200 and receipt_http.json()["status"] == "prepared", (
        receipt_http.text
    )
    from zebra_agent_api.responses import ApiResponse

    receipt = ApiResponse(receipt_http.status_code, receipt_http.json())
    http.close()
    assert receipt.body["previousRunId"] == state.protocol_run_id
    events = app.stores.events.list_for_session(task)
    answered = [e for e in events if e.event_type is EventType.CLARIFICATION_RESPONDED]
    assert len(answered) == 1 and answered[0].payload["content"] == "all"
    assert answered[0].payload["clarification_id"] == str(tool.tool_call_id)
    assert answered[0].payload["selected_choice"] is True
    commands = [e for e in events if e.event_type is EventType.SESSION_COMMAND_ACCEPTED]
    assert len(commands) == 2 and commands[-1].payload["kind"] == "message"
    assert len(gateway.requests) == 2
    assert app.stores.sessions.get_session(task).status is SessionStatus.AWAITING_TURN
    before_observation = app.stores.events.list_for_session(task)
    initial_new = replace(
        initial,
        body={**initial.body, "run": new_run},
        host_context=context,
        verified_host_grant=verified,
    )
    official_http_gate(
        app,
        initial_new,
        new_headers,
        [
            {
                "operation": new_headers["Idempotency-Key"],
                "clarificationId": str(tool.tool_call_id),
                "answer": "all",
            }
        ],
        metadata_dsn,
        tmp_path,
        monkeypatch,
    )
    assert app.stores.events.list_for_session(task) == before_observation
    assert len(gateway.requests) == 2
