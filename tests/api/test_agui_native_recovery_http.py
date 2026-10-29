"""Native deadline recovery remains observation-only and never invents browser input."""

import json
from datetime import UTC, datetime, timedelta
from time import sleep
from uuid import uuid4

from agent_core.application.mock_model import ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_storage.postgres.client_effect_recovery import ClientEffectRecovery
from zebra_agent_api.ag_ui_public_binding import resolve_public_continuation

from tests.agent_storage.test_postgres_projection_source_metadata import (
    metadata_dsn as _metadata_dsn,
)
from tests.api.agui_native_interaction_fixture import (
    native_fixture,
    official_http_gate,
    public_state,
)
from tests.api.test_agui_native_interaction_http import call, completion, input_value
from tests.worker.execution.worker_execution_support import _final_response

metadata_dsn = _metadata_dsn


def test_native_expiry_has_one_recovery_and_public_result_without_browser_receipt(
    metadata_dsn, tmp_path, monkeypatch
):
    import zebra_agent_worker.client_tool_gateway as client_gateway

    real_build = client_gateway.build_client_effect_request
    monkeypatch.setattr(
        client_gateway,
        "build_client_effect_request",
        lambda **kw: real_build(**{**kw, "effect_ttl": timedelta(milliseconds=50)}),
    )
    tool = call("app.ui.item.open", {"itemId": "expiry-owned"})
    profile_id = "zebra-reliable-v2-agui-1.0"
    app, task, run, initial, original, headers, forwarded, gateway, consumer, request = (
        native_fixture(
            metadata_dsn,
            tmp_path,
            monkeypatch,
            [
                ScriptedModelResponse(completion=completion(tool)),
                _final_response("Deadline observed"),
            ],
            profile_id=profile_id,
        )
    )
    assert (
        consumer().consume_once(worker_id="expiry-first", lease_ttl_seconds=30).status == "executed"
    )
    state = public_state(app, task, run, profile_id)
    binding = app.client_platform.client_sessions.get_active_run_binding(task)
    effect = app.client_platform.client_effects.list_pending(binding.client_session_id)[0]
    # A browser cannot forge the server-only expired terminal status.
    operation = uuid4()
    value = {"status": "expired", "result": {"reason": "browser_action_deadline_exceeded"}}
    before = app.stores.events.list_for_session(task)
    denied = request(
        "POST",
        "interaction",
        operation=operation,
        extra={"X-Zebra-Effect-Id": str(effect.effect_id)},
        body={
            "expectedRevision": app.stores.sessions.get_session(task).current_sequence,
            "input": input_value(
                task,
                state,
                forwarded,
                messages=[
                    {
                        "id": "tool-result:" + str(tool.tool_call_id),
                        "role": "tool",
                        "toolCallId": str(tool.tool_call_id),
                        "content": json.dumps(value),
                    }
                ],
            ),
            "receipt": {
                "receipt_id": str(operation),
                "effect_id": str(effect.effect_id),
                "idempotency_key": effect.idempotency_key,
                "request_digest": effect.request_digest,
                **value,
                "controller": True,
                "received_at": datetime.now(UTC).isoformat(),
            },
        },
    )
    assert denied.status_code in {400, 409, 422}, denied.body
    assert app.stores.events.list_for_session(task) == before
    sleep(max(0, (effect.expires_at - datetime.now(UTC)).total_seconds()) + 0.01)
    recovery = ClientEffectRecovery(
        metadata_dsn, deployment_namespace=app.stores.deployment_namespace
    )
    assert recovery.reconcile(session_id=task) == 1
    assert recovery.reconcile(session_id=task) == 0
    source_key = "client-effect-resume:recovery:" + str(effect.effect_id)
    events = app.stores.events.list_for_session(task)
    commands = [e for e in events if e.event_type is EventType.SESSION_COMMAND_ACCEPTED]
    assert len(commands) == 2 and commands[-1].idempotency_key == source_key
    assert not any(e.event_type is EventType.CLIENT_EFFECT_RECEIPT_ACCEPTED for e in events)
    assert app.client_platform.client_effect_receipts.read_receipt(effect.effect_id) is None
    assert (
        consumer().consume_once(worker_id="expiry-rebuilt", lease_ttl_seconds=30).status
        == "executed"
    )
    public_state(app, task, run, profile_id)
    source = app.stores.tasks.read_event_header_by_key(task, task, source_key)
    profile = app.agui_profiles.select(profile_id, "2")
    actual = resolve_public_continuation(
        app.stores.tasks,
        namespace=app.stores.deployment_namespace,
        task_id=task,
        internal_run_id=run,
        source=source,
        profile=profile,
    )
    assert actual.slice is not None
    # A separate native observer has no Controller and no access to A's input.
    from zebra_agent_api.routes import RouteAdapter, RouteRequest

    surface = initial.body["payload"]["surface"]
    observer = RouteAdapter(app).handle(
        RouteRequest(
            "POST",
            f"/v1/tasks/{task}/runs/{run}/client-surface",
            body={
                "grant": {**surface["grant"], "grant_id": str(uuid4())},
                "mount": {**surface["mount"], "mounted_actions": []},
                "task_capability_scope": [],
                "controller": False,
            },
            host_context=initial.host_context,
            verified_host_grant=initial.verified_host_grant,
        )
    )
    assert observer.status_code == 201, observer.body
    observer_headers = {
        **headers,
        "X-Zebra-Client-Session": observer.body["session_credential"],
        "X-Zebra-Client-Fence": "not-controller",
    }
    events = app.stores.events.list_for_session(task)
    unknown = request(
        "GET",
        "interaction",
        operation=operation,
        extra={"X-Zebra-Effect-Id": str(effect.effect_id), "X-Zebra-Client-Fence": "old"},
    )
    assert unknown.body["status"] == "not_observed", unknown.body
    official_http_gate(
        app,
        initial,
        observer_headers,
        [
            {
                "readOnly": True,
                "sourceKey": source_key,
                "publicRunId": actual.slice.run_id,
                "toolCallId": str(tool.tool_call_id),
                **value,
            }
        ],
        metadata_dsn,
        tmp_path,
        monkeypatch,
    )
    assert app.stores.events.list_for_session(task) == events
    assert len(gateway.requests) == 2
    assert len([e for e in events if e.event_type is EventType.SESSION_COMMAND_ACCEPTED]) == 2
