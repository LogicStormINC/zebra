"""Full durable client-effect chain: schedule -> wait -> receipt -> resume."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.client_run_bindings import ClientRunBinding
from agent_core.domain.client_sessions import ClientControlFence
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import (
    new_client_run_binding_id,
    new_client_session_id,
    new_message_id,
    new_session_id,
    new_task_id,
    new_tool_call_id,
)
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCallMetadata, ModelCompletion, ModelUsage
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessStopReason,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from zebra_agent_worker.client_effect_resume import recover_client_effect_wakeup
from zebra_agent_worker.client_tool_gateway import (
    ClientGatewayContext,
    ClientToolGateway,
)

CREATED_AT = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


class AllowAll:
    def evaluate_tool_call(self, _call):
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW, reason="t", policy_profile="t"
        )


class InMemoryDispatch:
    """Schedule-only store: effects persist, execution happens in the 'browser'."""

    def __init__(self) -> None:
        self.effects: list[object] = []

    def schedule(self, request, *, continuation, session_id):
        self.effects.append(request)
        from agent_core.ports.client_effect_dispatch import ClientEffectScheduleOutcome

        return ClientEffectScheduleOutcome(effect=request, created=True)

    def get_effect(self, effect_id):
        return next((e for e in self.effects if str(e.effect_id) == str(effect_id)), None)


def _completion(tool_call) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="Opening the item timeline.",
            created_at=CREATED_AT,
        ),
        tool_calls=(tool_call,),
        call_metadata=ModelCallMetadata(
            provider="p", model_name="m", latency_ms=1, cache_hit=False, cost_usd=0.0,
            usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        ),
    )


def _final() -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="The item timeline is open; analysis finished.",
            created_at=CREATED_AT,
        ),
        tool_calls=(),
        call_metadata=ModelCallMetadata(
            provider="p", model_name="m", latency_ms=1, cache_hit=False, cost_usd=0.0,
            usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        ),
    )


def test_client_tool_call_suspends_and_receipt_resumes() -> None:
    task_id = new_task_id()
    from agent_core.domain.tools import ToolCall

    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="app.ui.item.open",
        arguments={"itemId": "item-42"},
        created_at=CREATED_AT,
    )
    binding = ClientRunBinding(
        binding_id=new_client_run_binding_id(),
        task_id=task_id,
        run_id="run-1",
        client_session_id=new_client_session_id(),
        profile_digest="a" * 64,
        mounted_snapshot_digest="b" * 64,
        task_capability_scope=("app.ui.item.open",),
        allowed_actions=("app.ui.item.open",),
        binding_revision=1,
        created_at=CREATED_AT,
    )
    dispatch = InMemoryDispatch()
    gateway = ClientToolGateway(
        context=ClientGatewayContext(
            binding=binding,
            fence=ClientControlFence.issue(),
            session_id=new_session_id(),
            ui_revision=2,
            action_contract_digests={"app.ui.item.open": "c" * 64},
        ),
        dispatch=dispatch,
    )
    orchestrator = SingleAttemptOrchestrator(
        ScriptedModelGateway(
            responses=(ScriptedModelResponse(completion=_completion(call)),)
        ),
        AllowAll(),
        gateway,
    )

    suspended = HarnessLoop().run(
        HarnessTask(title="Open item", user_input="Open item 42."),
        orchestrator.run,
        created_at=CREATED_AT,
    )
    attempt = suspended.attempt_result
    assert attempt.outcome is HarnessAttemptOutcome.WAITING_EXTERNAL_TOOL
    assert attempt.metadata["stop_reason"] == "waiting_client_effect"
    assert suspended.run_result.stop_reason is HarnessStopReason.CLIENT_EFFECT_REQUIRED
    kinds = [event.event_type for event in suspended.events]
    assert EventType.CLIENT_EFFECT_SCHEDULED in kinds
    assert EventType.TOOL_EXECUTION_COMPLETED not in kinds
    assert len(dispatch.effects) == 1

    # The browser receipt lands as a durable HARNESS resume command.
    effect = dispatch.effects[0]
    scheduled_event = next(
        event
        for event in suspended.events
        if event.event_type is EventType.CLIENT_EFFECT_SCHEDULED
    )
    stream = list(suspended.events) + [
        scheduled_event.model_copy(
            update={
                "sequence": scheduled_event.sequence,
                "event_type": EventType.SESSION_COMMAND_ACCEPTED,
                "actor": EventActor.HARNESS,
                "payload": {
                    "command_id": "99999999-9999-4999-8999-999999999999",
                    "session_id": str(scheduled_event.session_id),
                    "kind": "resume",
                    "expected_revision": 0,
                    "idempotency_key": f"client-effect-resume:{effect.effect_id}",
                    "payload": {
                        "client_effect_result": {
                            "client_effect_id": str(effect.effect_id),
                            "tool_call_id": str(call.tool_call_id),
                            "action_name": "app.ui.item.open",
                            "status": "succeeded",
                            "result": {"opened": True},
                        }
                    },
                    "fingerprint": "f" * 64,
                },
            }
        )
    ]
    wakeup = recover_client_effect_wakeup(stream)
    assert wakeup is not None
    assert str(wakeup.tool_call.tool_call_id) == str(call.tool_call_id)

    resuming_orchestrator = SingleAttemptOrchestrator(
        ScriptedModelGateway(responses=(ScriptedModelResponse(completion=_final()),)),
        AllowAll(),
        gateway,  # the browser action must NOT re-execute
    )
    from agent_core.domain.sessions import Session as DomainSession
    from agent_core.harness import HarnessAttempt, HarnessContext
    from zebra_agent_worker.continuation_dispatch import run_continuation

    context = HarnessContext(
        task=HarnessTask(title="Open item", user_input="Open item 42."),
        session=DomainSession.create(title="resume", created_at=CREATED_AT),
        attempt=HarnessAttempt(number=2, started_at=CREATED_AT),
    )
    resumed = run_continuation(
        resuming_orchestrator,
        context,
        continuation=None,
        clarification=None,
        client_effect=wakeup,
    )
    assert resumed.outcome is HarnessAttemptOutcome.COMPLETED
    assert len(dispatch.effects) == 1  # handler executed exactly once
