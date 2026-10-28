"""Primary execution facts must not inherit the UI-only short callback ceiling."""

from time import monotonic, sleep

import pytest
from agent_core.domain.events import EventActor, EventType
from agent_core.harness import public_output_lifecycle as lifecycle
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy
from agent_core.ports.worker_progress import WorkerProgressTimeout
from agent_storage.postgres.task_io import current_task_io_deadline, task_io_deadline
from zebra_agent_worker.progress_recovery import recover_worker_progress
from zebra_agent_worker.public_output_runtime import publication_scope

from tests.agent_storage.test_worker_progress import append_progress, output_payload, seed_progress
from tests.worker import test_model_commentary_native as native_tests

native_dsn = native_tests.native_dsn


@pytest.mark.parametrize(
    "kind", [EventType.MODEL_RESPONSE_RECEIVED, EventType.MODEL_REQUEST_STARTED]
)
def test_critical_fact_has_own_finite_budget_and_one_durable_write(tmp_path, monkeypatch, kind):
    tasks, events, scope = seed_progress(tmp_path / "critical.sqlite")
    recovery = recover_worker_progress(
        tasks=tasks,
        namespace=scope.namespace,
        session_id=scope.task_id,
        ownership_check=lambda: None,
    )
    # Scale only wall time, keeping the actual real SQLite/callback composition.
    monkeypatch.setattr(lifecycle, "PUBLIC_OUTPUT_IO_SECONDS", 0.02)
    seen = []

    def append(event):
        seen.append(event)
        sleep(0.04)
        deadline = current_task_io_deadline()
        assert deadline is not None
        append_progress(events, scope, event.event_type, event.payload)
        # The source may commit before the acknowledgement crosses its deadline.
        if monotonic() >= deadline:
            raise TimeoutError("critical fact was constrained by UI deadline")

    sink = ProgressiveEventSink(
        recovery.persist_with(append),
        user_input="Read",
        policy=PublicOutputPolicy(),
        emission_scope=publication_scope,
    )
    payload = {"attempt_number": 1, "model_call_id": "original-model"}
    if kind is EventType.MODEL_RESPONSE_RECEIVED:
        payload.update(assistant_message="saved candidate", response_stage="candidate")
    sink(HarnessEventDraft(kind, EventActor.HARNESS, payload))
    sink.close()
    assert len(seen) == 1
    assert recovery.head.through_sequence == tasks.read_latest_run_header(scope.task_id).highwater
    assert sum(e.event_type == kind for e in events.list_for_session(scope.task_id)) == 1


def test_primary_fact_is_still_bounded_by_explicit_parent_deadline(tmp_path):
    tasks, events, scope = seed_progress(tmp_path / "parent.sqlite")
    recovery = recover_worker_progress(
        tasks=tasks,
        namespace=scope.namespace,
        session_id=scope.task_id,
        ownership_check=lambda: None,
    )
    calls = []

    def append(event):
        calls.append(event)
        sleep(0.05)
        with task_io_deadline(current_task_io_deadline()):
            append_progress(events, scope, event.event_type, event.payload)

    sink = ProgressiveEventSink(
        recovery.persist_with(append),
        user_input="Read",
        policy=PublicOutputPolicy(),
        emission_scope=publication_scope,
    )
    with pytest.raises(WorkerProgressTimeout):
        with task_io_deadline(monotonic() + 0.03):
            sink(
                HarnessEventDraft(
                    EventType.MODEL_RESPONSE_RECEIVED,
                    EventActor.HARNESS,
                    {
                        "attempt_number": 1,
                        "model_call_id": "bounded",
                        "response_stage": "candidate",
                    },
                )
            )
    assert len(calls) == 1
    assert len(events.list_for_session(scope.task_id)) == 2


def test_ui_publication_keeps_short_budget_and_cannot_write_after_timeout(tmp_path, monkeypatch):
    tasks, events, scope = seed_progress(tmp_path / "ui.sqlite")
    recovery = recover_worker_progress(
        tasks=tasks,
        namespace=scope.namespace,
        session_id=scope.task_id,
        ownership_check=lambda: None,
    )
    monkeypatch.setattr(lifecycle, "PUBLIC_OUTPUT_IO_SECONDS", 0.03)
    deadlines = []

    def append(event):
        deadlines.append(current_task_io_deadline())
        sleep(0.05)
        with task_io_deadline(current_task_io_deadline()):
            append_progress(events, scope, event.event_type, event.payload)

    sink = ProgressiveEventSink(
        recovery.persist_with(append),
        user_input="Read",
        policy=PublicOutputPolicy(),
        emission_scope=publication_scope,
    )
    with pytest.raises(WorkerProgressTimeout):
        sink(
            HarnessEventDraft(
                EventType.PUBLIC_OUTPUT, EventActor.HARNESS, output_payload(attempt=1)
            )
        )
    assert len(deadlines) == 1
    assert len(events.list_for_session(scope.task_id)) == 2


def test_native_primary_callback_can_finish_beyond_ui_limit(native_dsn):
    from tests.worker.test_model_commentary_native import native_state, restored

    state = native_state(native_dsn)
    recovery = restored(state)
    calls = []

    def append(event):
        calls.append(event)
        # Several native phases can exceed UI2s while each SQL transaction stays short.
        sleep(2.05)
        state.append(event)

    sink = ProgressiveEventSink(
        recovery.persist_with(append),
        user_input="Read",
        policy=PublicOutputPolicy(),
        emission_scope=publication_scope,
    )
    sink(
        HarnessEventDraft(
            EventType.MODEL_RESPONSE_RECEIVED,
            EventActor.HARNESS,
            {
                "attempt_number": 1,
                "model_call_id": "native-saved",
                "response_stage": "candidate",
                "assistant_message": "Saved response, no provider request",
            },
        )
    )
    sink.close()
    assert len(calls) == 1
    assert recovery.head.through_sequence == state.authority.expected_stream_revision
