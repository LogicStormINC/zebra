import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.sessions import Session
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.harness.hooks import NoopVerifier
from agent_core.harness.models import (
    HarnessAttempt,
    HarnessContext,
    HarnessEventBuffer,
    HarnessEventDraft,
    HarnessTask,
)
from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy
from agent_core.harness.tool_execution import execute_tool_call
from agent_runtime import LocalToolGateway
from agent_storage.sqlite import SQLiteEventStore
from agent_tools import ToolOutputProjector


@pytest.mark.parametrize(
    "body,limit,exit_code",
    [("private-small", 12000, 0), ("private-large-" * 1000, 256, 0), ("private-error", 256, 7)],
    ids=["small-success", "large-partial-success", "failed-command"],
)
def test_real_gateway_projection_receipt_durable_feedback_and_recovery(
    tmp_path: Path,
    body: str,
    limit: int,
    exit_code: int,
) -> None:
    persisted: list[str] = []

    def persist_output(content: str, _name: str) -> str:
        persisted.append(content)
        return "artifact://isolated-output"

    gateway = LocalToolGateway(
        tmp_path, output_projector=ToolOutputProjector(persist_output, max_model_characters=limit)
    )
    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="command.run",
        created_at=datetime.now(UTC),
        arguments={
            "command": [sys.executable, "-c", f"import sys; print({body!r}); sys.exit({exit_code})"]
        },
    )
    session = Session.create(title="Isolated projection receipt")
    database_path = tmp_path / "isolated-events.sqlite"
    store = SQLiteEventStore(database_path)
    sequence = 0

    def persist_event(draft: HarnessEventDraft) -> None:
        nonlocal sequence
        store.append(
            SessionEvent.create(
                session_id=session.session_id,
                sequence=sequence,
                event_type=draft.event_type,
                actor=draft.actor,
                created_at=datetime.now(UTC),
                payload=draft.payload,
            )
        )
        sequence += 1

    sink = ProgressiveEventSink(
        persist_event, user_input="Inspect workspace", policy=PublicOutputPolicy()
    )
    try:
        step = execute_tool_call(
            HarnessContext(
                HarnessTask(title=session.title, user_input="Inspect workspace"),
                session,
                HarnessAttempt(1, datetime.now(UTC)),
            ),
            call,
            tool_gateway=gateway,
            verifier=NoopVerifier(),
            emitted_events=HarnessEventBuffer(sink),
        )
    finally:
        sink.close()
        gateway.close()
    result = step.result
    assert len(persisted) == 1 and body in persisted[0]
    assert result.receipt is not None
    assert result.receipt.status == result.status.value
    assert result.receipt.output_bytes == len(result.output.encode("utf-8"))
    assert result.receipt.tool_name == "command.run" and result.receipt.scopes == ("zebra:local",)
    durable = SQLiteEventStore(database_path).list_for_session(session.session_id)
    event = next(
        event
        for event in durable
        if event.event_type in (EventType.TOOL_EXECUTION_COMPLETED, EventType.TOOL_EXECUTION_FAILED)
    )
    outputs = [event.payload for event in durable if event.event_type is EventType.PUBLIC_OUTPUT]
    assert outputs and all(
        output["meaningful"] is False and "evidence_basis" not in output for output in outputs
    )
    assert (
        "private-small" not in str(outputs)
        and "private-large" not in str(outputs)
        and "private-error" not in str(outputs)
    )
    if exit_code == 0:
        assert result.status is ToolCallStatus.EXECUTED
        facts = event.payload["metadata"]["public_facts"]
        assert facts["receipt"] == result.receipt.as_metadata()
        assert facts["output_truncated"] is result.metadata["output_truncated"]
        assert facts["output_truncated"] is (len(persisted[0]) > limit)
        assert str(result.receipt.output_bytes) in outputs[-1]["content"]
        if limit == 256:
            assert "partial" in outputs[-1]["content"]
        recovered = ProgressiveEventSink(
            persist_event,
            user_input="Inspect workspace",
            policy=PublicOutputPolicy(),
            prior_outputs=outputs,
        )
        try:
            terminal = HarnessEventDraft(event.event_type, event.actor, event.payload)
            recovered.observe_operation_result(terminal)
            recovered.observe_operation_result(terminal)
        finally:
            recovered.close()
        assert SQLiteEventStore(database_path).list_for_session(session.session_id) == durable
        assert len(persisted) == 1
    else:
        assert result.status is ToolCallStatus.FAILED
        assert "public_facts" not in event.payload["metadata"]
