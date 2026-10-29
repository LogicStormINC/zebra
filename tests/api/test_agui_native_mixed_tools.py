"""Actual sequential mixed native batch stops before later unexecuted proposals."""

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from agent_core.application.mock_model import ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.messages import MessageRole

from tests.agent_storage.test_postgres_projection_source_metadata import (
    metadata_dsn as _metadata_dsn,
)
from tests.api.agui_native_interaction_fixture import native_fixture, public_state
from tests.api.test_agui_native_interaction_http import call, completion, input_value
from tests.worker.execution.worker_execution_support import _final_response

metadata_dsn = _metadata_dsn


def test_mixed_native_batch_preserves_provider_safe_history_and_one_actual_effect(
    metadata_dsn, tmp_path, monkeypatch
):
    frontend = call("app.ui.item.open", {"itemId": "mixed-owned"})
    backend = call("command.run", {"command": [sys.executable, "-c", "print('must-not-run')"]})
    first = completion(frontend)
    mixed = replace(
        first,
        tool_calls=(frontend, backend),
        assistant_message=(
            first.assistant_message.model_copy(update={"tool_calls": (frontend, backend)})
        ),
    )
    app, task, run, initial, original, headers, forwarded, gateway, consumer, request = (
        native_fixture(
            metadata_dsn,
            tmp_path,
            monkeypatch,
            [
                ScriptedModelResponse(completion=mixed),
                _final_response("Actual effect acknowledged"),
            ],
        )
    )
    assert (
        consumer().consume_once(worker_id="mixed-first", lease_ttl_seconds=30).status == "executed"
    )
    state = public_state(app, task, run)
    assert state.pending_tools == {str(frontend.tool_call_id): frontend.name}
    events = app.stores.events.list_for_session(task)
    assert [
        e.payload["tool_call_id"] for e in events if e.event_type is EventType.TOOL_CALL_PROPOSED
    ] == [str(frontend.tool_call_id)]
    assert not any(e.event_type is EventType.APPROVAL_REQUESTED for e in events)
    binding = app.client_platform.client_sessions.get_active_run_binding(task)
    (effect,) = app.client_platform.client_effects.list_pending(binding.client_session_id)
    operation = uuid4()
    output = {"status": "succeeded", "result": {"opened": True}}
    receipt = {
        "receipt_id": str(operation),
        "effect_id": str(effect.effect_id),
        "idempotency_key": effect.idempotency_key,
        "request_digest": effect.request_digest,
        **output,
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
                    "id": "tool-result:" + str(frontend.tool_call_id),
                    "role": "tool",
                    "toolCallId": str(frontend.tool_call_id),
                    "content": json.dumps(output),
                }
            ],
        ),
    }
    accepted = request(
        "POST",
        "interaction",
        body=body,
        operation=operation,
        extra={"X-Zebra-Effect-Id": str(effect.effect_id)},
    )
    assert accepted.status_code == 202, accepted.body
    assert (
        consumer().consume_once(worker_id="mixed-rebuilt", lease_ttl_seconds=30).status
        == "executed"
    )
    public_state(app, task, run)
    assert len(gateway.requests) == 2, [
        (e.event_type.value, e.payload) for e in app.stores.events.list_for_session(task)
        if e.event_type in {EventType.TURN_FAILED, EventType.SESSION_FAILED}]

    pending = set()
    for message in gateway.requests[-1]:
        if message.role is MessageRole.ASSISTANT:
            assert not pending, "no new assistant call before prior calls receive results"
            pending.update(str(c.tool_call_id) for c in message.tool_calls)
        elif message.role is MessageRole.TOOL:
            assert str(message.tool_call_id) in pending, "no orphan provider tool result"
            pending.remove(str(message.tool_call_id))
    assert not pending
    assert all(
        str(c.tool_call_id) != str(backend.tool_call_id)
        for message in gateway.requests[-1]
        for c in message.tool_calls
    )
    events = app.stores.events.list_for_session(task)
    assert len([e for e in events if e.event_type is EventType.CLIENT_EFFECT_SCHEDULED]) == 1
    assert len([e for e in events if e.event_type is EventType.SESSION_COMMAND_ACCEPTED]) == 2
