"""Public callback admission is a call-site hook, never a payload classification."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelTextDelta
from agent_core.domain.stream_admission import RunStreamAdmission, StreamCapabilities, StreamMode
from agent_core.harness.model_step import HarnessModelStep
from agent_integrations.redis_transient_output import TransientOutputUnavailable
from zebra_agent_worker.transient_output_runtime import TransientDeltaSink, WorkerTransientCallGate

from tests.agent_core.test_transient_output_contract import authorization, generation


class PublicStreamingProvider:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("expected streaming callback")

    def complete_stream(self, _messages, *, tools=(), on_text_delta):
        on_text_delta(ModelTextDelta(index=0, content="  public "))
        return ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content="Full response",
                created_at=datetime.now(UTC),
            )
        )


def test_actual_public_hook_follows_durable_request_before_any_public_text():
    observed = []

    def admit(call, attempt):
        assert observed[-1].event_type is EventType.MODEL_REQUEST_STARTED
        assert observed[-1].payload["model_call_id"] == call
        assert observed[-1].payload["attempt_number"] == attempt
        observed.append("admitted")

    step = HarnessModelStep(event_sink=observed.append, public_call_started=admit)
    completion = step.request_completion([], PublicStreamingProvider(), allow_tools=True)
    assert observed[1] == "admitted"
    assert observed[2].event_type is EventType.MODEL_RESPONSE_DELTA
    assert completion.assistant_message.content == "Full response"


@pytest.mark.parametrize(
    "admission_mode,private",
    [
        (None, False),
        (StreamMode.LEGACY, False),
        (StreamMode.TRANSIENT_V2, True),
    ],
)
def test_injected_sink_preserves_legacy_but_suppresses_private_v2_callback(admission_mode, private):
    auth = authorization(generation())
    tasks, leases, port = Mock(), Mock(), Mock()
    tasks.read_task_header.return_value = Mock(
        strict_coverage=private, active_segment_id=auth.scope.generation.segment_id
    )
    admitted = (
        None
        if admission_mode is None
        else RunStreamAdmission(
            task_id=auth.scope.generation.task_id,
            run_id="run-1",
            mode=admission_mode,
            capabilities=StreamCapabilities(
                wire_version=2,
                provisional_draft_label=True,
                replace_message=True,
                reset_provisional=True,
                scoped_resume=True,
            ),
        )
    )
    gate = WorkerTransientCallGate(
        scope=auth.scope,
        fence=auth.lease_fence,
        request_sequence=0,
        tasks=tasks,
        leases=leases,
        load_admission=lambda: admitted,
        fresh_grant_expiry=lambda _: auth.grant_expires_at,
    )
    writer = TransientDeltaSink(port, lambda *_: gate, durable_anchor=lambda: 0)
    observed = []
    step = HarnessModelStep(
        event_sink=writer.wrap(observed.append), public_call_started=writer.start_public_call
    )
    completion = step.request_completion([], PublicStreamingProvider(), allow_tools=True)
    expected = [EventType.MODEL_REQUEST_STARTED]
    if not private:
        expected.append(EventType.MODEL_RESPONSE_DELTA)
    assert [event.event_type for event in observed] == expected
    if not private:
        assert observed[-1].payload["content_delta"] == "  public "
    assert completion.assistant_message.content == "Full response"
    port.activate.assert_not_called()
    port.publish.assert_not_called()


def test_failed_confirmed_v2_activation_suppresses_draft_without_repairing_durable_sink():
    auth = authorization(generation())
    gate, port = Mock(), Mock()
    gate.scope = auth.scope
    gate.stream_mode.return_value = StreamMode.TRANSIENT_V2
    gate.ordinary_v2.return_value = True
    gate.issue.side_effect = TransientOutputUnavailable("Grant disappeared after v2 admission")
    writer = TransientDeltaSink(port, lambda *_: gate, durable_anchor=lambda: 0)
    observed = []
    sink = writer.wrap(observed.append)

    # Actual call id is resolved by the hook; use a fresh fixture binding for that call.
    def open_call(call, attempt):
        gate.scope = auth.scope.model_copy(
            update={
                "generation": auth.scope.generation.model_copy(
                    update={"model_call_id": call, "message_id": f"message:{call}"}
                )
            }
        )
        return gate

    writer._open = open_call
    step = HarnessModelStep(event_sink=sink, public_call_started=writer.start_public_call)
    completion = step.request_completion([], PublicStreamingProvider(), allow_tools=True)
    assert writer._failed
    assert [event.event_type for event in observed] == [EventType.MODEL_REQUEST_STARTED]
    assert completion.assistant_message.content == "Full response"


def test_actual_coalescer_reset_drops_retired_provider_callback():
    from agent_core.harness.stream_deltas import TextDeltaCoalescer

    events = []
    coalescer = TextDeltaCoalescer(events.append, attempt_number=1, characters=2, seconds=None)
    coalescer.reset("first")
    coalescer.emit("first", ModelTextDelta(index=0, content="first"))
    coalescer.reset("next")
    coalescer.emit("first", ModelTextDelta(index=1, content="late old"))
    coalescer.emit("next", ModelTextDelta(index=0, content="next"))
    assert [event.payload["content_delta"] for event in events] == ["first", "next"]


@pytest.mark.parametrize("failure", ["admission_timeout", "header_timeout", "unknown_privacy"])
def test_unknown_initial_admission_or_v2_eligibility_never_falls_back_to_durable_delta(failure):
    from agent_core.harness.orchestration_events import model_response_event

    auth = authorization(generation())
    tasks, leases, port = Mock(), Mock(), Mock()
    admitted = RunStreamAdmission(
        task_id=auth.scope.generation.task_id,
        run_id="run-1",
        mode=StreamMode.TRANSIENT_V2,
        capabilities=StreamCapabilities(
            wire_version=2,
            provisional_draft_label=True,
            replace_message=True,
            reset_provisional=True,
            scoped_resume=True,
        ),
    )
    loader = Mock(return_value=admitted)
    if failure == "admission_timeout":
        loader.side_effect = TimeoutError("initial durable admission lookup timed out")
    elif failure == "header_timeout":
        tasks.read_task_header.side_effect = TimeoutError("v2 source eligibility timed out")
    else:
        tasks.read_task_header.return_value = Mock(
            strict_coverage=None, active_segment_id=auth.scope.generation.segment_id
        )
    gates = []

    def open_call(call, attempt):
        scope = auth.scope.model_copy(
            update={
                "generation": auth.scope.generation.model_copy(
                    update={"model_call_id": call, "message_id": f"message:{call}"}
                )
            }
        )
        gate = WorkerTransientCallGate(
            scope=scope,
            fence=auth.lease_fence,
            request_sequence=0,
            tasks=tasks,
            leases=leases,
            load_admission=loader,
            fresh_grant_expiry=lambda _: auth.grant_expires_at,
        )
        gates.append(gate)
        return gate

    writer = TransientDeltaSink(port, open_call, durable_anchor=lambda: 0)
    observed = []
    sink = writer.wrap(observed.append)
    step = HarnessModelStep(event_sink=sink, public_call_started=writer.start_public_call)
    completion = step.request_completion([], PublicStreamingProvider(), allow_tools=True)
    sink(model_response_event(completion, attempt_number=1, response_stage="candidate"))
    assert writer._failed and gates[0]._closed
    assert [event.event_type for event in observed] == [
        EventType.MODEL_REQUEST_STARTED,
        EventType.MODEL_RESPONSE_RECEIVED,
    ]
    assert observed[-1].payload["assistant_message"] == "Full response"
    port.activate.assert_not_called()
    port.publish.assert_not_called()
    if failure == "header_timeout":
        loader.assert_called_once()  # The actual immutable v2 admission was resolved first.
        tasks.read_task_header.assert_called_once()


@pytest.mark.parametrize("later_mode", [StreamMode.LEGACY])
def test_resolved_v2_run_cannot_downgrade_mode_on_next_public_callback(later_mode):
    from agent_core.harness.orchestration_events import model_response_event

    auth = authorization(generation())
    port = Mock()
    modes = iter((StreamMode.TRANSIENT_V2, later_mode))

    def open_call(call, attempt):
        gate = Mock()
        gate.scope = auth.scope.model_copy(
            update={
                "generation": auth.scope.generation.model_copy(
                    update={"model_call_id": call, "message_id": f"message:{call}"}
                )
            }
        )
        gate.stream_mode.return_value = next(modes)
        gate.ordinary_v2.return_value = True
        gate.issue.return_value = auth.model_copy(update={"scope": gate.scope})
        return gate

    writer = TransientDeltaSink(port, open_call, durable_anchor=lambda: 0)
    observed = []
    sink = writer.wrap(observed.append)
    step = HarnessModelStep(event_sink=sink, public_call_started=writer.start_public_call)
    for _ in range(2):
        completion = step.request_completion([], PublicStreamingProvider(), allow_tools=True)
        sink(model_response_event(completion, attempt_number=1))
    assert writer._failed
    assert port.activate.call_count == 1 and port.publish.call_count == 1
    assert [event.event_type for event in observed] == [
        EventType.MODEL_REQUEST_STARTED,
        EventType.MODEL_RESPONSE_RECEIVED,
        EventType.MODEL_REQUEST_STARTED,
        EventType.MODEL_RESPONSE_RECEIVED,
    ]
