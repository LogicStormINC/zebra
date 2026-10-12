"""Consume a native bounded tail page without one primary projection write per Event."""

from time import monotonic
from typing import TYPE_CHECKING

from agent_core.application.session_projection import apply_event as apply_session_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.ports.workspace_projection_store import WorkerProjectionBatchPort
from agent_storage.postgres.task_io import current_task_io_deadline

if TYPE_CHECKING:
    from zebra_agent_worker.execution_events import DurableHarnessEventRecorder


def project_tail_batches(recorder: "DurableHarnessEventRecorder") -> None:
    transaction = recorder._worker_projection_transaction
    reader = recorder._tail_reader
    assert isinstance(transaction, WorkerProjectionBatchPort) and reader is not None
    highwater = recorder._tail_highwater
    while True:
        recorder._ownership_check()
        authority = recorder.worker_mutation_authority
        assert authority is not None
        after = recorder.session.current_sequence
        if authority.expected_stream_revision != after:
            raise ValueError("recorder tail authority revision diverges")
        page = reader(authority, highwater)
        if (page.session_id != recorder.session.session_id or page.after_sequence != after
                or (highwater is not None and page.highwater != highwater)):
            raise ValueError("recorder tail page changed its admitted frontier")
        highwater = page.highwater
        recorder._tail_highwater = highwater
        # Reader admission is bounded; never accumulate the complete history.
        for start in range(0, len(page.events), 128):
            events = page.events[start:start + 128]
            session, workspace = recorder.session, recorder.workspace
            for event in events:
                if (event.session_id != session.session_id
                        or event.sequence != session.current_sequence + 1):
                    raise ValueError("recorder tail page skips canonical revisions")
                recorder._ownership_check()
                deadline = current_task_io_deadline()
                if deadline is not None and monotonic() >= deadline:
                    raise TimeoutError("Recorder canonical tail deadline exceeded")
                session = apply_session_event(session, event)
                workspace = apply_workspace_event(workspace, event)
            authority = recorder.worker_mutation_authority
            assert authority is not None
            committed = transaction.project_persisted_worker_events(
                tuple(events), session, workspace, authority=authority,
            )
            recorder.accept_committed_events(
                tuple(events), session=committed.session, workspace=committed.workspace,
            )
        if recorder.session.current_sequence == highwater:
            recorder._tail_highwater = None
            return
        if not page.events:
            raise ValueError("recorder tail page made no progress")
