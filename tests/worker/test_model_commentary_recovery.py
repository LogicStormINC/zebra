"""Crash source/partial chunks/checkpoint commit gaps resume without re-running models."""

from unittest.mock import Mock

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseLostError
from agent_core.harness.model_commentary import commentary_outputs, plan_response
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports.task_projection_checkpoints import CheckpointConflict
from zebra_agent_worker.progress_recovery import recover_worker_progress

from tests.agent_core.test_model_commentary import source
from tests.agent_storage.test_worker_progress import seed_progress


def fixture(tmp_path, monkeypatch):
    tasks, events, scope = seed_progress(tmp_path / "commentary.sqlite")
    sequence = 1
    appended = []

    def append(draft):
        nonlocal sequence
        sequence += 1
        events.append(
            SessionEvent.create(
                session_id=scope.task_id,
                sequence=sequence,
                event_type=draft.event_type,
                actor=EventActor.HARNESS,
                payload=draft.payload,
            )
        )
        appended.append(draft)

    monkeypatch.setattr(events, "list_for_session", lambda _: pytest.fail("whole-history read"))
    return tasks, scope, append, appended


def recovery(tasks, scope, check=lambda: None):
    return recover_worker_progress(
        tasks=tasks, namespace=scope.namespace, session_id=scope.task_id, ownership_check=check
    )


@pytest.mark.parametrize("committed_chunks", [0, 1, 2])
def test_crash_source_to_output_resumes_exact_missing_chunks(
    tmp_path, monkeypatch, committed_chunks
):
    tasks, scope, append, rows = fixture(tmp_path, monkeypatch)
    payload = plan_response(source(" 🐎\n" * 2001), 0)
    drafts = commentary_outputs(payload)
    append(HarnessEventDraft(EventType.MODEL_RESPONSE_RECEIVED, EventActor.HARNESS, payload))
    for draft in drafts[:committed_chunks]:
        append(draft)
    recovered = recovery(tasks, scope)
    pages = Mock(wraps=tasks.read_event_page)
    monkeypatch.setattr(tasks, "read_event_page", pages)
    recovered.persist_with(append)
    published = [row for row in rows if row.event_type is EventType.PUBLIC_OUTPUT]
    assert published == list(drafts)
    assert recovered.head.state.pending_commentary is None
    assert (
        recovered.head.state.commentary_reserved_count
        == recovered.head.state.commentary_published_count
        == len(drafts)
    )
    assert recovered.head.state.published_count == 0
    assert all(
        c.kwargs["limit"] <= 256 and c.kwargs["max_bytes"] <= 1048576 for c in pages.call_args_list
    )
    before = len(rows)
    recovery(tasks, scope).persist_with(append)
    assert len(rows) == before


def test_unknown_commit_then_checkpoint_failure_never_reappends_chunk(tmp_path, monkeypatch):
    tasks, scope, append, rows = fixture(tmp_path, monkeypatch)
    payload = plan_response(source("x" * 4001), 0)
    append(HarnessEventDraft(EventType.MODEL_RESPONSE_RECEIVED, EventActor.HARNESS, payload))
    recovered = recovery(tasks, scope)

    def unknown(draft):
        append(draft)
        raise TimeoutError("commit response lost")

    with pytest.raises(TimeoutError):
        recovered.persist_with(unknown)
    recovered = recovery(tasks, scope)
    recovered.persist_with(append)
    assert [d for d in rows if d.event_type is EventType.PUBLIC_OUTPUT] == list(
        commentary_outputs(payload)
    )


def test_lease_loss_before_gap_repair_and_before_next_chunk(tmp_path, monkeypatch):
    tasks, scope, append, rows = fixture(tmp_path, monkeypatch)
    payload = plan_response(source("x" * 4001), 0)
    append(HarnessEventDraft(EventType.MODEL_RESPONSE_RECEIVED, EventActor.HARNESS, payload))
    recovered = recovery(tasks, scope)
    recovered.ownership_check = Mock(side_effect=LeaseLostError("stale fence"))
    with pytest.raises(LeaseLostError):
        recovered.persist_with(append)
    assert len(rows) == 1


def test_cancelled_run_never_repairs_abandoned_publication(tmp_path, monkeypatch):
    tasks, scope, append, rows = fixture(tmp_path, monkeypatch)
    payload = plan_response(source(), 0)
    append(HarnessEventDraft(EventType.MODEL_RESPONSE_RECEIVED, EventActor.HARNESS, payload))
    append(HarnessEventDraft(EventType.SESSION_CANCELLED, EventActor.USER, {}))
    restored = recovery(tasks, scope)
    restored.persist_with(append)
    assert len(rows) == 2 and restored.head.state.terminal
    assert restored.head.state.pending_commentary is not None


def test_forged_commentary_rejected_before_primary_append(tmp_path, monkeypatch):
    tasks, scope, append, rows = fixture(tmp_path, monkeypatch)
    restored = recovery(tasks, scope)
    draft = commentary_outputs(plan_response(source(), 0))[0]
    with pytest.raises(CheckpointConflict, match="no durable pending"):
        restored.persist_with(append)(draft)
    assert rows == []
