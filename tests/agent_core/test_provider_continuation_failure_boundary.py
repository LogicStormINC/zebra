"""No-network proof: uncertain native requests must not dispatch fallback."""

from datetime import UTC, datetime

import pytest
from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelContextWindow
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import HarnessAttemptOutcome
from agent_core.harness.provider_continuation import ProviderContinuationUncertainError
from agent_core.ports.model_gateway import ModelResponseRejectedError
from zebra_agent_worker.execution_errors import exception_attempt_result


class OfflineGateway:
    context_window = ModelContextWindow(
        profile_name="offline", context_tokens=10_000, max_output_tokens=100,
        compaction_reserve_tokens=50, protocol_reserve_tokens=50,
        compaction_trigger_reserve_tokens=50,
    )

    def __init__(self, error):
        self.error, self.calls = error, []

    def complete_from_reference(self, reference, messages, *, tools=()):
        self.calls.append("native")
        if self.error is not None:
            raise self.error
        return self.response()

    def complete(self, messages, *, tools=()):
        self.calls.append("ordinary")
        return self.response()

    @staticmethod
    def response():
        return ModelCompletion(assistant_message=message(MessageRole.ASSISTANT, "done"))


def message(role=MessageRole.USER, content="offline"):
    return SessionMessage(message_id=new_message_id(), role=role, content=content,
                          created_at=datetime.now(UTC))


def step(tracked):
    events = []
    return HarnessModelStep(
        provider_continuation=ProviderContinuationRef(
            reference_id="offline", provider="test", model_name="offline", source_hash="a" * 64),
        event_sink=events.append if tracked else None,
    ), events


@pytest.mark.parametrize("tracked", [False, True])
@pytest.mark.parametrize("error", [TimeoutError("uncertain"), ValueError("invalid result"),
    ModelResponseRejectedError("invalid", phase="decode", retryable=False)])
def test_uncertain_failure_suspends_without_fallback(tracked, error):
    model, events = step(tracked)
    gateway = OfflineGateway(error)
    with pytest.raises(ProviderContinuationUncertainError) as caught:
        model.request_completion([message()], gateway, allow_tools=False, response_repair_limit=0)
    assert gateway.calls == ["native"]
    assert caught.value.__cause__ is error
    result = exception_attempt_result(caught.value, {"contract_verification_prompted": True})
    assert result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.metadata["retryable"] is False
    assert result.metadata["contract_verification_prompted"] is True
    assert model._provider_continuation is None
    assert sum(e.event_type.value == "model_request_started" for e in events) == int(tracked)


@pytest.mark.parametrize("tracked", [False, True])
def test_predispatch_unsupported_capability_allows_one_fallback(tracked):
    model, events = step(tracked)
    gateway = OfflineGateway(NotImplementedError("not sent"))
    result = model.request_completion([message()], gateway, allow_tools=False)
    assert result.assistant_message.content == "done"
    assert gateway.calls == ["native", "ordinary"]
    assert model._provider_continuation is None
    assert sum(e.event_type.value == "model_request_started" for e in events) == int(tracked)


@pytest.mark.parametrize("tracked", [False, True])
def test_success_and_cancellation_do_not_issue_second_request(tracked):
    model, _ = step(tracked)
    gateway = OfflineGateway(None)
    model.request_completion([message()], gateway, allow_tools=False)
    assert gateway.calls == ["native"]
    model, _ = step(tracked)
    gateway = OfflineGateway(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        model.request_completion([message()], gateway, allow_tools=False)
    assert gateway.calls == ["native"] and model._provider_continuation is None
