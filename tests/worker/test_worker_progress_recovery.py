"""Native Worker progress recovery, rather than a scan of prior messages."""

from dataclasses import asdict
from unittest.mock import Mock

import pytest
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.leases import LeaseLostError
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_output import PublicOutputPolicy
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.progress_recovery import recover_worker_progress

from tests.agent_storage.test_worker_progress import append_progress, output_payload, seed_progress


def recover(tasks, scope, **options):
    return recover_worker_progress(
        tasks=tasks,
        namespace=scope.namespace,
        session_id=scope.task_id,
        ownership_check=lambda: None,
        **options,
    )


def test_recovery_restores_real_attempt_and_policy_without_session_scan(tmp_path, monkeypatch):
    tasks, events, scope = seed_progress(tmp_path / "restore.sqlite")
    frozen = PublicOutputPolicy(version="frozen", expression_max_calls=2)
    append_progress(events, scope, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 3})
    append_progress(
        events,
        scope,
        EventType.MODEL_REQUEST_STARTED,
        {
            "model_call_id": "main",
            "public_output_policy": asdict(frozen),
        },
    )
    append_progress(
        events,
        scope,
        EventType.MODEL_RESPONSE_DELTA,
        {
            "attempt_number": 3,
            "model_call_id": "main",
            "delta_index": 0,
            "content_delta": "I found",
        },
    )
    append_progress(
        events,
        scope,
        EventType.MODEL_RESPONSE_RECEIVED,
        {
            "assistant_message": "Tool calls proposed.",
        },
    )
    append_progress(
        events,
        scope,
        EventType.MODEL_REQUEST_STARTED,
        {
            "model_call_id": "expression",
            "purpose": "public_expression",
        },
    )
    append_progress(events, scope, EventType.PUBLIC_OUTPUT, output_payload(attempt=3))
    monkeypatch.setattr(events, "list_for_session", lambda _: pytest.fail("full history read"))
    restored = recover(tasks, scope)
    assert restored.head.state.attempt_number == 3
    assert restored.head.state.model_spoke
    assert restored.head.state.expression_calls_used == 1
    assert restored.policy(PublicOutputPolicy(version="changed")) == frozen
    assert restored.output_published("public:2:found")
    assert restored.receipts_covered(("read:1", "missing")) == frozenset({"read:1"})
    page = Mock(wraps=tasks.read_event_page)
    monkeypatch.setattr(tasks, "read_event_page", page)
    assert recover(tasks, scope).head == restored.head
    page.assert_not_called()


def test_recovery_advances_bounded_prefix_without_losing_tail(tmp_path, monkeypatch):
    tasks, events, scope = seed_progress(tmp_path / "bounded.sqlite")
    for index in range(300):
        append_progress(events, scope, EventType.SESSION_TITLE_UPDATED, {"title": str(index)})
    page = Mock(wraps=tasks.read_event_page)
    monkeypatch.setattr(tasks, "read_event_page", page)
    with pytest.raises(CheckpointNotReady, match="bounded prefix"):
        recover(tasks, scope, max_pages=1)
    assert page.call_count == 1
    assert tasks.read_worker_progress(scope).through_sequence == 256
    recovered = recover(tasks, scope, max_pages=1)
    assert recovered.head.through_sequence == 301
    assert all(call.kwargs["limit"] <= 256 for call in page.call_args_list)
    assert all(call.kwargs["max_bytes"] <= 1_048_576 for call in page.call_args_list)


def test_lease_loss_cannot_prepare_progress_or_append_public_output(tmp_path):
    tasks, events, scope = seed_progress(tmp_path / "fenced.sqlite")

    def lost():
        raise LeaseLostError("lease lost")

    with pytest.raises(LeaseLostError):
        recover_worker_progress(
            tasks=tasks, namespace="local", session_id=scope.task_id, ownership_check=lost
        )
    with pytest.raises(CheckpointNotReady):
        tasks.read_worker_progress(scope)
    restored = recover(tasks, scope)
    restored.ownership_check = lost
    sink = Mock()
    with pytest.raises(LeaseLostError):
        restored.persist_with(sink)(
            HarnessEventDraft(
                EventType.PUBLIC_OUTPUT, EventActor.HARNESS, output_payload(attempt=1)
            )
        )
    sink.assert_not_called()


def test_superseded_run_rejects_output_before_the_append(tmp_path):
    tasks, events, scope = seed_progress(tmp_path / "superseded.sqlite")
    restored = recover(tasks, scope)
    command = SessionCommand(
        session_id=scope.task_id,
        kind=SessionCommandKind.RUN,
        expected_revision=1,
        idempotency_key="new-run",
        payload={"run_id": "new-run"},
    )
    append_progress(events, scope, EventType.SESSION_COMMAND_ACCEPTED, command.event_payload())
    sink = Mock()
    with pytest.raises(ExecutionInterrupted, match="superseded"):
        restored.persist_with(sink)(
            HarnessEventDraft(
                EventType.PUBLIC_OUTPUT, EventActor.HARNESS, output_payload(attempt=1)
            )
        )
    sink.assert_not_called()
    assert recover(tasks, scope).head.scope.run_id == "new-run"


@pytest.mark.parametrize("kind", [EventType.MODEL_RESPONSE_DELTA, EventType.PUBLIC_OUTPUT])
def test_old_attempt_is_rejected_before_the_canonical_append(tmp_path, kind):
    tasks, events, scope = seed_progress(tmp_path / "attempt.sqlite")
    append_progress(events, scope, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 3})
    restored = recover(tasks, scope)
    sink = Mock()
    payload = (
        output_payload(attempt=1)
        if kind is EventType.PUBLIC_OUTPUT
        else {
            "attempt_number": 1,
            "content_delta": "Old attempt",
        }
    )
    with pytest.raises(CheckpointConflict, match="Attempt"):
        restored.persist_with(sink)(HarnessEventDraft(kind, EventActor.HARNESS, payload))
    sink.assert_not_called()
    assert tasks.read_worker_progress(scope) == restored.head


def test_failed_checkpoint_after_canonical_append_is_recovered_without_reappending(
    tmp_path, monkeypatch
):
    tasks, events, scope = seed_progress(tmp_path / "append.sqlite")
    restored = recover(tasks, scope)
    advance = tasks.advance_worker_progress
    monkeypatch.setattr(
        tasks, "advance_worker_progress", Mock(side_effect=TimeoutError("commit unknown"))
    )
    calls = []

    def append(draft):
        calls.append(draft)
        append_progress(events, scope, draft.event_type, draft.payload)

    with pytest.raises(TimeoutError):
        restored.persist_with(append)(
            HarnessEventDraft(
                EventType.PUBLIC_OUTPUT, EventActor.HARNESS, output_payload(attempt=1)
            )
        )
    monkeypatch.setattr(tasks, "advance_worker_progress", advance)
    recovered = recover(tasks, scope)
    assert recovered.head.state.published_count == 1
    assert recovered.output_published("public:2:found")
    assert len(calls) == 1


def test_latest_run_identity_is_not_inferred_from_task_uuid(tmp_path):
    tasks, events, scope = seed_progress(tmp_path / "identity.sqlite")
    command = SessionCommand(
        session_id=scope.task_id,
        kind=SessionCommandKind.RUN,
        expected_revision=1,
        idempotency_key="missing-run",
        payload={},
    )
    append_progress(events, scope, EventType.SESSION_COMMAND_ACCEPTED, command.event_payload())
    with pytest.raises(CheckpointNotReady, match="Run identity"):
        recover(tasks, scope)


def test_persist_checks_latest_run_once_on_each_side_of_canonical_append(tmp_path, monkeypatch):
    tasks, events, scope = seed_progress(tmp_path / "fresh-sides.sqlite")
    restored = recover(tasks, scope)
    read = tasks.read_latest_run_header
    frontiers = []

    def latest(task_id):
        run = read(task_id)
        frontiers.append(run.highwater)
        return run

    monkeypatch.setattr(tasks, "read_latest_run_header", latest)

    def append(draft):
        append_progress(events, scope, draft.event_type, draft.payload)

    restored.persist_with(append)(
        HarnessEventDraft(EventType.SESSION_TITLE_UPDATED, EventActor.HARNESS, {"title": "Fresh"})
    )
    assert frontiers == [1, 2]
    assert restored.head == tasks.read_worker_progress(scope)
    assert restored.head.through_sequence == 2
    assert len(events.list_for_session(scope.task_id)) == 3


def test_run_superseded_during_append_still_stops_post_append_repair(tmp_path):
    tasks, events, scope = seed_progress(tmp_path / "superseded-during-append.sqlite")
    restored = recover(tasks, scope)
    calls = []

    def append(draft):
        calls.append(draft)
        append_progress(events, scope, draft.event_type, draft.payload)
        command = SessionCommand(
            session_id=scope.task_id, kind=SessionCommandKind.RUN,
            expected_revision=2, idempotency_key="replacement",
            payload={"run_id": "replacement"},
        )
        append_progress(events, scope, EventType.SESSION_COMMAND_ACCEPTED, command.event_payload())

    with pytest.raises(ExecutionInterrupted, match="superseded"):
        restored.persist_with(append)(
            HarnessEventDraft(
                EventType.SESSION_TITLE_UPDATED, EventActor.HARNESS, {"title": "Committed"}
            )
        )
    assert len(calls) == 1
    assert restored.head.through_sequence == 1
    assert tasks.read_latest_run_header(scope.task_id).run_id == "replacement"
