"""Actual public-call interception preserves full response and progress observation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.modeling import ModelTextDelta
from agent_core.domain.stream_admission import (
    RunStreamAdmission,
    StreamCapabilities,
    StreamMode,
    TransientCapacityPolicy,
)
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy
from agent_core.harness.stream_deltas import TextDeltaCoalescer
from agent_integrations.redis_transient_output import TransientOutputUnavailable
from zebra_agent_worker.transient_output_runtime import (
    TransientDeltaSink,
    WorkerTransientCallGate,
    split_transient_text,
)

from tests.agent_core.test_transient_output_contract import authorization, generation


def draft(kind, **payload):
    return HarnessEventDraft(
        kind, EventActor.HARNESS, {"model_call_id": "call-1", "attempt_number": 1, **payload}
    )


@pytest.mark.parametrize("content", ["🙂中" * 16000, '\\"\n\t' * 16000, "  "])
def test_exact_json_split_preserves_unicode_whitespace_and_contiguous_offset(content):
    auth = authorization(generation())
    frames = tuple(split_transient_text(auth, content, offset=7, anchor=13))
    assert "".join(frame.content_delta for frame in frames) == content
    assert [frame.offset for frame in frames] == list(range(7, 7 + len(frames)))
    assert all(len(frame.wire_bytes()) <= 16 * 1024 for frame in frames)
    assert all(
        frame.presentation == "provisional_draft" and frame.durable_anchor == 13 for frame in frames
    )


def test_gate_unknown_admission_private_coverage_and_fresh_full_fence():
    auth = authorization(generation())
    tasks, leases, admission, grant = Mock(), Mock(), Mock(), Mock()
    tasks.read_task_header.return_value = Mock(
        strict_coverage=False, active_segment_id=auth.scope.generation.segment_id
    )
    tasks.read_latest_run_header.return_value = Mock(
        run_id="run-1", stop=None, control_only=False, anchor=object(), strict_coverage=False
    )
    tasks.read_event_page.return_value = Mock(
        events=(
            Mock(
                segment_id=auth.scope.generation.segment_id,
                event=Mock(
                    event_type=EventType.MODEL_REQUEST_STARTED,
                    actor=EventActor.HARNESS,
                    payload={"model_call_id": "call-1", "attempt_number": 1},
                ),
            ),
        ),
        has_more=False,
    )
    leases.get.return_value = Mock(fence=auth.lease_fence, expires_at=auth.lease_expires_at)
    grant.return_value = auth.grant_expires_at
    gate = WorkerTransientCallGate(
        scope=auth.scope,
        fence=auth.lease_fence,
        request_sequence=0,
        tasks=tasks,
        leases=leases,
        load_admission=admission,
        fresh_grant_expiry=grant,
    )
    admission.return_value = None
    with pytest.raises(TransientOutputUnavailable, match="frozen v2"):
        gate.issue()
    admission.return_value = RunStreamAdmission(
        task_id=auth.scope.generation.task_id,
        run_id="run-1",
        mode=StreamMode.TRANSIENT_V2,
        capacity_policy=TransientCapacityPolicy(),
        capacity_digest=TransientCapacityPolicy().digest,
        capabilities=StreamCapabilities(
            wire_version=2,
            provisional_draft_label=True,
            replace_message=True,
            reset_provisional=True,
            scoped_resume=True,
        ),
    )
    for private in (None, True):
        tasks.read_task_header.return_value.strict_coverage = private
        with pytest.raises(TransientOutputUnavailable, match="ordinary public"):
            gate.issue()
    tasks.read_task_header.return_value.strict_coverage = False
    leases.get.return_value.fence = auth.lease_fence.model_copy(update={"owner_instance_id": "old"})
    with pytest.raises(TransientOutputUnavailable, match="full lease"):
        gate.issue()
    leases.get.return_value.fence = auth.lease_fence
    issued = gate.issue()
    gate.resolve(issued)
    with pytest.raises(TransientOutputUnavailable, match="unknown"):
        gate.resolve(issued.model_copy())
    gate.close()
    with pytest.raises(TransientOutputUnavailable, match="closed"):
        gate.issue()


@pytest.mark.parametrize("count", [10, 100])
def test_zero_durable_delta_calls_at_fixed_time_and_progress_observed(count):
    auth = authorization(generation())
    port, gate, durable = Mock(), Mock(), Mock()
    gate.scope = auth.scope
    gate.stream_mode.return_value = StreamMode.TRANSIENT_V2
    gate.issue.return_value = auth
    writer = TransientDeltaSink(port, lambda *_: gate, durable_anchor=lambda: 9)
    progress = ProgressiveEventSink(
        writer.wrap(durable), user_input="x", policy=PublicOutputPolicy(expression_max_calls=0)
    )
    progress(draft(EventType.MODEL_REQUEST_STARTED))
    writer.start_public_call("call-1", 1)
    coalescer = TextDeltaCoalescer(progress, attempt_number=1, characters=5, seconds=None)
    for index in range(count):
        coalescer.emit("call-1", ModelTextDelta(index=index, content=" a "))
    coalescer.flush()
    progress(draft(EventType.MODEL_RESPONSE_RECEIVED, assistant_message="full durable response"))
    assert progress._model_spoke
    assert all(
        call.args[0].event_type is not EventType.MODEL_RESPONSE_DELTA
        for call in durable.call_args_list
    )
    assert port.activate.call_count == 1 and gate.issue.call_count == 1
    frames = [call.args[1] for call in port.publish.call_args_list]
    assert "".join(frame.content_delta for frame in frames) == " a " * count
    assert [frame.offset for frame in frames] == list(range(len(frames)))
    assert (
        durable.call_args_list[-1].args[0].payload["assistant_message"] == "full durable response"
    )
    gate.close.assert_called()
    port.invalidate.assert_called()
    progress.close()


def test_unknown_payload_category_cannot_admit_private_or_expression_call():
    port, gate, durable = Mock(), Mock(), Mock()
    writer = TransientDeltaSink(port, lambda *_: gate, durable_anchor=lambda: 9)
    sink = writer.wrap(durable)
    event = draft(
        EventType.MODEL_RESPONSE_DELTA,
        content_delta="private",
        category="ordinary_public_text",
        coverage_mode=False,
    )
    sink(event)
    assert durable.call_args.args[0] is event
    port.publish.assert_not_called()
    port.activate.assert_not_called()


def test_transport_failure_closes_and_never_falls_back_to_durable_partial():
    auth = authorization(generation())
    port, gate, durable = Mock(), Mock(), Mock()
    gate.scope = auth.scope
    gate.stream_mode.return_value = StreamMode.TRANSIENT_V2
    gate.issue.return_value = auth
    port.publish.side_effect = TransientOutputUnavailable("uncertain append")
    writer = TransientDeltaSink(port, lambda *_: gate, durable_anchor=lambda: 9)
    sink = writer.wrap(durable)
    writer.start_public_call("call-1", 1)
    for index in range(3):
        sink(draft(EventType.MODEL_RESPONSE_DELTA, delta_index=index, content_delta="partial"))
    sink(draft(EventType.MODEL_RESPONSE_RECEIVED, assistant_message="full response"))
    assert port.publish.call_count == 1
    assert [call.args[0].event_type for call in durable.call_args_list] == [
        EventType.MODEL_RESPONSE_RECEIVED
    ]
    assert gate.close.call_count == 1


def test_renewal_checks_gate_again_only_at_authority_deadline():
    auth = authorization(generation())
    soon = auth.model_copy(update={"expires_at": datetime.now(UTC) + timedelta(milliseconds=500)})
    gate, port = Mock(), Mock()
    gate.scope = auth.scope
    gate.stream_mode.return_value = StreamMode.TRANSIENT_V2
    gate.issue.side_effect = [soon, auth]
    writer = TransientDeltaSink(port, lambda *_: gate, durable_anchor=lambda: 0)
    writer.start_public_call("call-1", 1)
    writer.wrap(Mock())(draft(EventType.MODEL_RESPONSE_DELTA, content_delta=" a "))
    assert gate.issue.call_count == 2 and port.activate.call_count == 2


def test_retired_v2_delta_cannot_enter_next_call_durable_sink():
    auth = authorization(generation())
    first, second, port, durable = Mock(), Mock(), Mock(), Mock()
    first.scope = auth.scope
    first.stream_mode.return_value = StreamMode.TRANSIENT_V2
    first.issue.return_value = auth
    second_auth = auth.model_copy(
        update={
            "scope": auth.scope.model_copy(
                update={
                    "generation": auth.scope.generation.model_copy(
                        update={
                            "model_call_id": "next",
                            "message_id": "message:next",
                            "generation_id": "next",
                        }
                    )
                }
            )
        }
    )
    second.scope = second_auth.scope
    second.stream_mode.return_value = StreamMode.TRANSIENT_V2
    second.issue.return_value = second_auth
    gates = iter((first, second))
    writer = TransientDeltaSink(port, lambda *_: next(gates), durable_anchor=lambda: 0)
    sink = writer.wrap(durable)
    writer.start_public_call("call-1", 1)
    sink(draft(EventType.MODEL_RESPONSE_RECEIVED, assistant_message="first full"))
    writer.start_public_call("next", 1)
    sink(draft(EventType.MODEL_RESPONSE_DELTA, content_delta="late old draft"))
    assert port.publish.call_count == 0
    assert [call.args[0].event_type for call in durable.call_args_list] == [
        EventType.MODEL_RESPONSE_RECEIVED
    ]


def test_transient_wrapper_never_blocks_publication_timer_on_visual_lock(monkeypatch):
    from threading import Event
    from time import monotonic

    from agent_core.harness import public_output_lifecycle as lifecycle
    from zebra_agent_worker.public_output_runtime import publication_scope

    from tests.worker.test_public_output_deadline import hold

    monkeypatch.setattr(lifecycle, "PUBLIC_OUTPUT_IO_SECONDS", 0.12)
    monkeypatch.setattr(lifecycle, "PUBLIC_OUTPUT_CLOSE_SECONDS", 0.5)
    writer = TransientDeltaSink(Mock(), Mock(), durable_anchor=lambda: 0)
    published = Event()
    wrapped = writer.wrap(lambda _: published.set())
    progress = ProgressiveEventSink(
        wrapped,
        user_input="x",
        policy=PublicOutputPolicy(wait_seconds=0.01),
        emission_scope=publication_scope,
    )
    owner, release = hold(writer._lock)
    progress.operation_started("slow")
    timer = progress._timer
    assert timer is not None
    started = monotonic()
    try:
        assert published.wait(0.2)
        progress.close()
        assert monotonic() - started < 0.3 and not timer.is_alive()
        assert progress._timer_error is None and owner.is_alive()
    finally:
        release.set()
        owner.join(1)
        timer.join(1)
        progress.close()


def test_transient_close_wait_has_one_short_deadline(monkeypatch):
    from time import monotonic

    from agent_core.harness import public_output_lifecycle as lifecycle

    from tests.worker.test_public_output_deadline import hold

    monkeypatch.setattr(lifecycle, "PUBLIC_OUTPUT_IO_SECONDS", 0.12)
    writer = TransientDeltaSink(Mock(), Mock(), durable_anchor=lambda: 0)
    owner, release = hold(writer._lock)
    started = monotonic()
    try:
        with pytest.raises(TimeoutError):
            writer.close()
        assert monotonic() - started < 0.3 and owner.is_alive()
    finally:
        release.set()
        owner.join(1)
        writer.close()


@pytest.mark.parametrize(
    "terminal", [EventType.SESSION_COMPLETED, EventType.SESSION_FAILED, EventType.SESSION_CANCELLED]
)
def test_source_terminal_without_model_response_cannot_reconstruct_old_callback(terminal):
    auth = authorization(generation())
    tasks, leases = Mock(), Mock()
    admitted = RunStreamAdmission(
        task_id=auth.scope.generation.task_id,
        run_id="run-1",
        mode=StreamMode.TRANSIENT_V2,
        capacity_policy=TransientCapacityPolicy(),
        capacity_digest=TransientCapacityPolicy().digest,
        capabilities=StreamCapabilities(
            wire_version=2,
            provisional_draft_label=True,
            replace_message=True,
            reset_provisional=True,
            scoped_resume=True,
        ),
    )
    tasks.read_task_header.return_value = Mock(
        strict_coverage=False, active_segment_id=auth.scope.generation.segment_id
    )
    tasks.read_latest_run_header.return_value = Mock(
        run_id="run-1", stop=None, control_only=False, anchor=object(), strict_coverage=False
    )
    tasks.read_event_page.return_value = Mock(
        has_more=False,
        events=(
            Mock(
                segment_id=auth.scope.generation.segment_id,
                event=Mock(
                    actor=EventActor.HARNESS,
                    event_type=EventType.MODEL_REQUEST_STARTED,
                    payload={"model_call_id": "call-1", "attempt_number": 1},
                ),
            ),
            Mock(event=Mock(event_type=terminal, payload={})),
        ),
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
    with pytest.raises(TransientOutputUnavailable, match="Session is terminal"):
        gate.issue()
    leases.get.assert_not_called()


def test_old_v2_missing_capacity_stays_transient_only_before_rejection():
    auth = authorization(generation())
    gate = Mock()
    gate.stream_mode.return_value = StreamMode.TRANSIENT_V2
    gate.ordinary_v2.return_value = True
    gate.scope = auth.scope
    gate.issue.side_effect = TransientOutputUnavailable("no frozen capacity policy")
    persisted = []
    writer = TransientDeltaSink(Mock(), lambda *_: gate, durable_anchor=lambda: 0)
    writer.start_public_call("call-1", 1)
    sink = writer.wrap(persisted.append)
    sink(draft(EventType.MODEL_RESPONSE_DELTA, content_delta="private draft"))
    sink(draft(EventType.MODEL_RESPONSE_RECEIVED, content="durable complete"))
    assert [event.event_type for event in persisted] == [EventType.MODEL_RESPONSE_RECEIVED]
    assert writer._failed and gate.close.called
