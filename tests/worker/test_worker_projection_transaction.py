from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import apply_event as apply_session_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseFence
from agent_core.ports import WorkerMutationAuthority, WorkerProjectionCommitResult
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.tool_run_index import ToolRunIndexer


def test_recorder_uses_injected_fenced_projection_transaction() -> None:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Atomic Worker projection",
            user_input="continue",
            workspace_root=Path("/tmp/atomic-worker"),
        )
    )
    event_store = Mock()
    event_store.read_since.return_value = []
    projection_store = Mock()
    workspace_store = Mock()
    transaction = Mock()
    transaction.commit_worker_event.side_effect = (
        lambda event, session, workspace, **_: WorkerProjectionCommitResult(
            event=event,
            session=session,
            workspace=workspace,
        )
    )
    authority = WorkerMutationAuthority(
        deployment_namespace="cloud-a",
        session_id=bootstrap.session.session_id,
        lease_fence=LeaseFence(
            control_plane_epoch=uuid4(),
            fencing_token=7,
            owner_instance_id="worker-a",
        ),
        expected_stream_revision=bootstrap.session.current_sequence,
    )
    recorder = DurableHarnessEventRecorder(
        session=bootstrap.session,
        workspace=rebuild_workspace(list(bootstrap.events)),
        event_store=event_store,
        projection_store=projection_store,
        workspace_store=workspace_store,
        model_call_indexer=ModelCallIndexer(Mock()),
        tool_run_indexer=ToolRunIndexer(Mock(), Mock()),
        worker_projection_transaction=transaction,
        worker_mutation_authority=authority,
    )

    first = recorder.append(
        EventType.HARNESS_ATTEMPT_STARTED,
        EventActor.HARNESS,
        {"attempt_number": 1},
        created_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
    )
    second = recorder.append(
        EventType.SESSION_COMPLETED,
        EventActor.HARNESS,
        {"summary": "done"},
        created_at=datetime(2026, 7, 29, 10, 1, tzinfo=UTC),
    )

    assert transaction.commit_worker_event.call_count == 2
    first_call, second_call = transaction.commit_worker_event.call_args_list
    assert first_call.args[0] == first
    assert first_call.args[1].current_sequence == first.sequence
    assert first_call.args[2].current_sequence == first.sequence
    assert first_call.kwargs["authority"] == authority
    assert second_call.args[0] == second
    assert second_call.kwargs["authority"].expected_stream_revision == first.sequence
    event_store.append.assert_not_called()
    projection_store.save_session.assert_not_called()
    workspace_store.save_workspace.assert_not_called()
    assert recorder.session.current_sequence == second.sequence
    assert recorder.workspace.current_sequence == second.sequence


def test_recorder_adopts_canonical_event_after_lost_ack_retry() -> None:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Canonical Worker projection",
            user_input="continue",
            workspace_root=Path("/tmp/canonical-worker"),
        )
    )
    workspace = rebuild_workspace(list(bootstrap.events))
    requested = SessionEvent.create(
        session_id=bootstrap.session.session_id,
        sequence=bootstrap.session.current_sequence + 1,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
        idempotency_key="attempt-started",
        created_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
    )
    canonical = requested.model_copy(
        update={
            "event_id": uuid4(),
            "created_at": datetime(2026, 7, 29, 9, 59, tzinfo=UTC),
        }
    )
    transaction = Mock()
    transaction.commit_worker_event.return_value = WorkerProjectionCommitResult(
        event=canonical,
        session=apply_session_event(bootstrap.session, canonical),
        workspace=apply_workspace_event(workspace, canonical),
    )
    authority = WorkerMutationAuthority(
        deployment_namespace="cloud-a",
        session_id=bootstrap.session.session_id,
        lease_fence=LeaseFence(
            control_plane_epoch=uuid4(),
            fencing_token=7,
            owner_instance_id="worker-a",
        ),
        expected_stream_revision=bootstrap.session.current_sequence,
    )
    recorder = DurableHarnessEventRecorder(
        session=bootstrap.session,
        workspace=workspace,
        event_store=Mock(),
        projection_store=Mock(),
        workspace_store=Mock(),
        model_call_indexer=ModelCallIndexer(Mock()),
        tool_run_indexer=ToolRunIndexer(Mock(), Mock()),
        worker_projection_transaction=transaction,
        worker_mutation_authority=authority,
    )

    stored = recorder.append_event(requested)

    assert stored == canonical
    assert recorder.events == (canonical,)
    assert recorder.session == apply_session_event(bootstrap.session, canonical)
    assert recorder.workspace == apply_workspace_event(workspace, canonical)


@pytest.mark.parametrize("missing", ["transaction", "authority"])
def test_recorder_rejects_partial_projection_transaction_configuration(
    missing: str,
) -> None:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Invalid atomic Worker projection",
            user_input="continue",
            workspace_root=Path("/tmp/invalid-atomic-worker"),
        )
    )
    transaction = None if missing == "transaction" else Mock()
    authority = (
        None
        if missing == "authority"
        else WorkerMutationAuthority(
            deployment_namespace="cloud-a",
            session_id=bootstrap.session.session_id,
            lease_fence=LeaseFence(
                control_plane_epoch=uuid4(),
                fencing_token=1,
                owner_instance_id="worker-a",
            ),
            expected_stream_revision=bootstrap.session.current_sequence,
        )
    )

    with pytest.raises(ValueError, match="configured together"):
        DurableHarnessEventRecorder(
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            event_store=Mock(),
            projection_store=Mock(),
            workspace_store=Mock(),
            model_call_indexer=ModelCallIndexer(Mock()),
            tool_run_indexer=ToolRunIndexer(Mock(), Mock()),
            worker_projection_transaction=transaction,
            worker_mutation_authority=authority,
        )
