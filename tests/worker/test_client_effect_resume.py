"""Client effect wakeup recovery and resume acceptance."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id, new_session_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCallMetadata, ModelCompletion, ModelUsage
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.sessions import Session
from agent_core.domain.tools import ToolCallStatus
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessContext,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from zebra_agent_worker.client_effect_resume import (
    client_effect_wakeup_tool_result,
    recover_client_effect_wakeup,
)
from zebra_agent_worker.continuation_dispatch import run_continuation

NOW = datetime(2026, 8, 25, tzinfo=UTC)
SESSION = new_session_id()


def _event(sequence: int, event_type: EventType, actor: EventActor, payload: dict):
    return SessionEvent.create(
        session_id=SESSION,
        sequence=sequence,
        event_type=event_type,
        actor=actor,
        payload=payload,
        created_at=NOW,
        idempotency_key=f"k{sequence}",
    )


def _stream() -> list[SessionEvent]:
    return [
        _event(
            0,
            EventType.CLIENT_EFFECT_SCHEDULED,
            EventActor.TOOL,
            {
                "attempt_number": 1,
                "tool_name": "app.ui.item.open",
                "tool_call_id": "11111111-2222-3333-4444-555555555555",
                "client_effect_id": "e-1",
                "action_name": "app.ui.item.open",
                "assistant_message": "Opening the item.",
                "model_calls_used": 1,
                "tool_calls_executed": 0,
                "conversation": [],
            },
        ),
        _event(
            1,
            EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
            EventActor.HARNESS,
            {"reason": "waiting_client_effect", "client_effect_ids": ["e-1"]},
        ),
        _event(
            2,
            EventType.SESSION_COMMAND_ACCEPTED,
            EventActor.HARNESS,
            {
                "kind": "resume",
                "command_id": "99999999-9999-4999-8999-999999999999",
                "session_id": str(SESSION),
                "expected_revision": 0,
                "idempotency_key": "resume-9",
                "fingerprint": "f" * 64,
                "payload": {
                    "client_effect_result": {
                        "client_effect_id": "e-1",
                        "tool_call_id": "11111111-2222-3333-4444-555555555555",
                        "action_name": "app.ui.item.open",
                        "status": "succeeded",
                        "result": {"opened": True},
                    }
                },
            },
        ),
    ]


class AllowAll:
    def evaluate_tool_call(self, _call):
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW, reason="t", policy_profile="t"
        )


class UnusedGateway:
    def execute(self, call):  # pragma: no cover - resume path needs no tool
        raise AssertionError("resume must not re-execute the client action")


def test_wakeup_restores_the_original_tool_identity() -> None:
    wakeup = recover_client_effect_wakeup(_stream())
    assert wakeup is not None
    assert str(wakeup.tool_call.tool_call_id) == "11111111-2222-3333-4444-555555555555"
    assert wakeup.tool_call.name == "app.ui.item.open"
    assert wakeup.status == "succeeded"
    result = client_effect_wakeup_tool_result(wakeup)
    assert result.status is ToolCallStatus.EXECUTED
    assert result.metadata["client_effect_id"] == "e-1"


def test_unknown_effect_resume_fails_closed() -> None:
    stream = _stream()
    stream[2] = _event(
        2,
        EventType.SESSION_COMMAND_ACCEPTED,
        EventActor.HARNESS,
        {
            "kind": "resume",
            "command_id": "99999999-9999-4999-8999-999999999999",
            "session_id": str(SESSION),
            "expected_revision": 0,
            "idempotency_key": "resume-9",
            "fingerprint": "f" * 64,
            "payload": {
                "client_effect_result": {
                    "client_effect_id": "never-scheduled",
                    "status": "succeeded",
                }
            },
        },
    )
    try:
        recover_client_effect_wakeup(stream)
        raise AssertionError("expected failure")
    except ValueError:
        pass


def test_run_continuation_resumes_without_reexecution() -> None:
    wakeup = recover_client_effect_wakeup(_stream())
    assert wakeup is not None
    final_completion = ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="Item opened; analysis complete.",
            created_at=NOW,
        ),
        tool_calls=(),
        call_metadata=ModelCallMetadata(
            provider="p",
            model_name="m",
            latency_ms=1,
            cache_hit=False,
            cost_usd=0.0,
            usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        ),
    )
    orchestrator = SingleAttemptOrchestrator(
        ScriptedModelGateway(
            responses=(ScriptedModelResponse(completion=final_completion),)
        ),
        AllowAll(),
        UnusedGateway(),
    )
    context = HarnessContext(
        task=HarnessTask(title="t", user_input="u"),
        session=Session.create(title="t", created_at=NOW),
        attempt=HarnessAttempt(number=1, started_at=NOW),
    )
    resumed = run_continuation(
        orchestrator,
        context,
        continuation=None,
        clarification=None,
        client_effect=wakeup,
    )
    assert resumed.outcome is HarnessAttemptOutcome.COMPLETED
