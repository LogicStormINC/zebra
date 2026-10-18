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
from agent_core.domain.tools import ToolCall, ToolCallStatus
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


def test_old_receipt_cannot_resume_new_browser_wait():
    from zebra_agent_worker.client_effect_continuation import has_trusted_client_effect_resume

    events = _stream()
    assert has_trusted_client_effect_resume(events)
    events.append(_event(3, EventType.SESSION_RESUMED, EventActor.HARNESS, {"reason": "done"}))
    events.append(
        _event(
            4,
            EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
            EventActor.HARNESS,
            {"reason": "waiting_client_effect", "client_effect_ids": ["e-2"]},
        )
    )
    assert not has_trusted_client_effect_resume(events)


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
                "continuation_metadata": {},
                "model_calls_used": 1,
                "tool_calls_executed": 0,
                "conversation": [],
            },
        ),
        _event(
            1,
            EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
            EventActor.HARNESS,
            {
                "reason": "waiting_client_effect",
                "client_effect_ids": ["e-1"],
                "metadata": {
                    "continuations": {
                        "e-1": {
                            "assistant_message": "Opening the item.",
                            "continuation_metadata": {},
                            "model_calls_used": 1,
                            "tool_calls_executed": 1,
                            "conversation": [
                                SessionMessage(
                                    message_id=new_message_id(),
                                    role=MessageRole.USER,
                                    content="Open the item.",
                                    created_at=NOW,
                                ).model_dump(mode="json"),
                                SessionMessage(
                                    message_id=new_message_id(),
                                    role=MessageRole.ASSISTANT,
                                    content="Opening the item.",
                                    created_at=NOW,
                                    tool_calls=(
                                        ToolCall(
                                            tool_call_id="11111111-2222-3333-4444-555555555555",
                                            name="app.ui.item.open",
                                            arguments={},
                                            created_at=NOW,
                                            provider_call_id="call_browser_1",
                                            provider_tool_name="app__ui__item__open",
                                            provider_arguments={},
                                        ),
                                    ),
                                    metadata={"provider_reasoning_required": True},
                                ).model_dump(mode="json"),
                            ],
                        }
                    }
                },
            },
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
        return PolicyDecision(decision=PolicyDecisionType.ALLOW, reason="t", policy_profile="t")


class UnusedGateway:
    def execute(self, call):  # pragma: no cover - resume path needs no tool
        raise AssertionError("resume must not re-execute the client action")


def test_wakeup_restores_the_original_tool_identity() -> None:
    wakeup = recover_client_effect_wakeup(_stream())
    assert wakeup is not None
    assert str(wakeup.tool_call.tool_call_id) == "11111111-2222-3333-4444-555555555555"
    assert wakeup.tool_call.provider_call_id == "call_browser_1"
    assert wakeup.tool_call.name == "app.ui.item.open"
    assert wakeup.status == "succeeded"
    assert wakeup.assistant_message == "Opening the item."
    assert wakeup.model_calls_used == 1
    assert wakeup.tool_calls_executed == 1
    assert [message.content for message in wakeup.conversation] == [
        "Open the item.",
        "Opening the item.",
    ]
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
        ScriptedModelGateway(responses=(ScriptedModelResponse(completion=final_completion),)),
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
    assert resumed.metadata["client_effect_rebased"] is True
    assert resumed.metadata["durable_action_fingerprints"]


def test_verification_and_deduplication_survive_both_receipt_branches():
    from dataclasses import replace
    from unittest.mock import Mock

    state = {
        "mutation_epoch": 2, "mutation_resource_epochs": {"A": 1, "B": 2},
        "verified_resource_epochs": {"B": 2},
        "mutation_resource_evidence": {"A": {"commit_version": "v1"}},
        "read_fingerprint_epochs": {"read-B": 2},
        "contract_verification_prompted": True,
        "post_mutation_verification_prompted": True,
        "durable_action_fingerprints": ["prior-action"],
    }
    stream = _stream()
    stream[1].payload["metadata"]["continuations"]["e-1"]["continuation_metadata"] = state
    wakeup = recover_client_effect_wakeup(stream)
    assert wakeup is not None and wakeup.metadata == state
    for safe in (False, True):
        messages = list(wakeup.conversation)
        messages[-1] = messages[-1].model_copy(update={"metadata": {}}) if safe else messages[-1]
        orchestrator = Mock()
        from types import SimpleNamespace

        run_continuation(orchestrator, SimpleNamespace(attempt=SimpleNamespace(started_at=NOW)),
                         continuation=None, clarification=None,
                         client_effect=replace(wakeup, conversation=tuple(messages)))
        method = (orchestrator.continue_completed_tool if safe
                  else orchestrator.continue_completed_tools)
        restored = method.call_args.kwargs["metadata"]
        assert all(restored[key] == value for key, value in state.items()
                   if key != "durable_action_fingerprints")
        assert "prior-action" in restored["durable_action_fingerprints"]
        assert len(restored["durable_action_fingerprints"]) == 2
        from agent_core.harness.final_completion import _contract_verification_satisfied

        assert not _contract_verification_satisfied(restored, read_only_tools=frozenset({"read"}))


def test_legacy_or_missing_mutation_scope_pauses_before_model():
    from dataclasses import replace
    from unittest.mock import Mock

    wakeup = recover_client_effect_wakeup(_stream())
    for metadata in (None, {"mutation_epoch": 2, "verified_mutation_epoch": 2}):
        orchestrator = Mock()
        result = run_continuation(orchestrator, None, continuation=None, clarification=None,
                                  client_effect=replace(wakeup, metadata=metadata))
        assert result.outcome is HarnessAttemptOutcome.SUSPENDED
        assert result.metadata["delivery_assessment"]["status"] == "partial"
        assert result.metadata["retryable"] is False
        assert not orchestrator.mock_calls


def test_consumed_receipt_cannot_resume_after_pause_or_terminal():
    boundaries = (
        (EventType.SESSION_SUSPENDED, {"reason": "verification_required"}),
        (EventType.TURN_COMPLETED, {"turn_id": "t"}),
        (EventType.SESSION_CANCELLED, {"reason": "user"}),
        (EventType.CLARIFICATION_REQUESTED, {}),
    )
    # Recovery reads already validated durable events. Isolate consumption logic.
    from types import SimpleNamespace

    for kind, payload in boundaries:
        stream = _stream()
        stream += [SimpleNamespace(event_type=EventType.HARNESS_ATTEMPT_STARTED,
                                   actor=EventActor.HARNESS, payload={"client_effect_id": "e-1"}),
                   SimpleNamespace(event_type=kind, actor=EventActor.HARNESS, payload=payload)]
        assert recover_client_effect_wakeup(stream) is None
        # A duplicate accepted command cannot hide the earlier consumption.
        stream.append(stream[2])
        assert recover_client_effect_wakeup(stream) is None


def test_uncertain_receipt_start_pauses_without_second_model_or_start():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from zebra_agent_worker.continuation_lifecycle import start_recovered_continuation

    stream = _stream() + [SimpleNamespace(
        event_type=EventType.HARNESS_ATTEMPT_STARTED, actor=EventActor.HARNESS,
        payload={"client_effect_id": "e-1"})]
    wakeup = recover_client_effect_wakeup(stream)
    orchestrator, recorder = Mock(), Mock()
    result = run_continuation(orchestrator, None, continuation=None, clarification=None,
                              client_effect=wakeup)
    assert result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.metadata["stop_reason"] == "client_effect_recovery_uncertain"
    claim = object()
    assert start_recovered_continuation(
        claim, continuation=None, clarification=None, client_effect=wakeup,
        event_store=Mock(), recovery_service=Mock(), started_at=NOW, recorder=recorder,
    ) is claim
    assert not orchestrator.mock_calls and not recorder.mock_calls


def test_fast_receipt_before_own_wait_marker_preserves_frozen_state():
    stream = _stream()
    stream[0].payload["continuation_metadata"] = {"contract_verification_prompted": True}
    # Crash before waiting: scheduled-event snapshot alone must be sufficient.
    wakeup = recover_client_effect_wakeup([stream[0], stream[2]])
    assert wakeup.metadata == {"contract_verification_prompted": True}
    # Receipt before the finalizer's waiting event is not already consumed.
    assert recover_client_effect_wakeup([stream[0], stream[2], stream[1]]) is not None


def test_fenced_receipt_start_is_written_before_dispatch():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from zebra_agent_worker.continuation_lifecycle import start_recovered_continuation

    claim = SimpleNamespace(lease=object(), recovery=SimpleNamespace(
        session=SimpleNamespace(session_id=SESSION, current_sequence=4)))
    recorder, recovery = Mock(), Mock()
    result = start_recovered_continuation(
        claim, continuation=None, clarification=None,
        client_effect=recover_client_effect_wakeup(_stream()),
        event_store=Mock(), recovery_service=recovery, started_at=NOW, recorder=recorder,
    )
    marker = recorder.append_event.call_args.args[0]
    assert marker.sequence == 5 and marker.payload["client_effect_id"] == "e-1"
    assert marker.payload["completed_continuation"] is True
    assert result is not None


def test_eager_scheduled_event_has_snapshot_before_wait_finalization():
    import json

    from agent_core.domain.tools import ToolResult

    class DeferredGateway(UnusedGateway):
        def execute(self, call):
            return ToolResult(tool_call_id=call.tool_call_id, status=ToolCallStatus.EXECUTED,
                              output="scheduled", metadata={
                                  "client_effect_deferred": True, "client_effect_id": "e-1"})

    call = ToolCall(tool_call_id="11111111-2222-3333-4444-555555555555",
                    name="app.ui.item.open", arguments={}, created_at=NOW)
    completion = ModelCompletion(assistant_message=SessionMessage(
        message_id=new_message_id(), role=MessageRole.ASSISTANT,
        content="Opening", tool_calls=(call,), created_at=NOW), tool_calls=(call,))
    saved = []
    orchestrator = SingleAttemptOrchestrator(
        ScriptedModelGateway(responses=(ScriptedModelResponse(completion=completion),)),
        AllowAll(), DeferredGateway(), event_sink=lambda draft: saved.append(
            _event(len(saved), draft.event_type, draft.actor,
                   json.loads(json.dumps(draft.payload)))),
    )
    result = orchestrator.run(HarnessContext(
        task=HarnessTask(title="t", user_input="Open the item"),
        session=Session.create(title="t", created_at=NOW),
        attempt=HarnessAttempt(number=1, started_at=NOW)))
    assert result.outcome is HarnessAttemptOutcome.WAITING_EXTERNAL_TOOL
    scheduled = next(e for e in saved if e.event_type is EventType.CLIENT_EFFECT_SCHEDULED)
    assert scheduled.payload["continuation_metadata"] is not None
    assert scheduled.payload["model_calls_used"] == 1
    assert scheduled.payload["tool_calls_executed"] == 1
    assert scheduled.payload["conversation"]


def test_receipt_error_retains_verification_state_but_not_private_metadata():
    from dataclasses import replace

    from zebra_agent_worker.execution_completion import run_worker_continuation
    from zebra_agent_worker.execution_errors import error_metadata

    wakeup = replace(recover_client_effect_wakeup(_stream()), metadata={
        "mutation_epoch": 1, "mutation_resource_epochs": {"A": 1},
        "contract_verification_prompted": True, "private": "must not persist",
    })
    state = error_metadata(TimeoutError("hidden"), None, wakeup)
    assert state["mutation_resource_epochs"] == {"A": 1}
    assert state["contract_verification_prompted"] is True and "private" not in state
    # The wrapper must pass the client continuation to the shared error classifier.
    from unittest.mock import Mock

    orchestrator = Mock()
    orchestrator.continue_completed_tools.side_effect = TimeoutError("offline")
    orchestrator.close.return_value = None
    from types import SimpleNamespace

    result = run_worker_continuation(
        orchestrator, SimpleNamespace(attempt=SimpleNamespace(started_at=NOW)),
        continuation=None, clarification=None, child_wakeup=None, client_effect=wakeup,
        release_gateway=lambda: None,
    )
    assert result.metadata["mutation_resource_epochs"] == {"A": 1}
