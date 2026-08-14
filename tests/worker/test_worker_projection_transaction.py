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


def test_recorder_rejects_cloud_projections_not_derived_from_event() -> None:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Invalid cloud aggregate projection",
            user_input="continue",
            workspace_root=Path("/tmp/invalid-cloud-aggregate"),
        )
    )
    workspace = rebuild_workspace(list(bootstrap.events))
    event = SessionEvent.create(
        session_id=bootstrap.session.session_id,
        sequence=bootstrap.session.current_sequence + 1,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
        created_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
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
        worker_projection_transaction=Mock(),
        worker_mutation_authority=authority,
    )
    expected_workspace = apply_workspace_event(workspace, event)
    tampered_workspace = expected_workspace.model_copy(update={"workspace_root": "/tmp/tampered"})

    with pytest.raises(ValueError, match="projections do not match Event replay"):
        recorder.accept_committed_aggregate(
            event,
            session=apply_session_event(bootstrap.session, event),
            workspace=tampered_workspace,
        )


def test_committed_aggregate_uses_fenced_indexes() -> None:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Cloud aggregate indexes",
            user_input="continue",
            workspace_root=Path("/tmp/cloud-aggregate-indexes"),
        )
    )
    workspace = rebuild_workspace(list(bootstrap.events))
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
    model_indexer = Mock()
    tool_indexer = Mock()
    recorder = DurableHarnessEventRecorder(
        session=bootstrap.session,
        workspace=workspace,
        event_store=Mock(),
        projection_store=Mock(),
        workspace_store=Mock(),
        model_call_indexer=model_indexer,
        tool_run_indexer=tool_indexer,
        worker_projection_transaction=Mock(),
        worker_mutation_authority=authority,
    )
    event = SessionEvent.create(
        session_id=bootstrap.session.session_id,
        sequence=bootstrap.session.current_sequence + 1,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
        created_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
    )

    recorder.accept_committed_events(
        (event,),
        session=apply_session_event(bootstrap.session, event),
        workspace=apply_workspace_event(workspace, event),
    )

    model_indexer.index_worker_event.assert_called_once_with(event, authority=authority)
    tool_indexer.index_worker_event.assert_called_once_with(event, authority=authority)
    model_indexer.index_event.assert_not_called()
    tool_indexer.index_event.assert_not_called()


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


def test_accept_persisted_event_uses_fenced_indexing_and_advances_projections() -> None:
    """Cloud guard events must never reach the legacy upsert indexing path.

    Regression for the approved-continuation wedge: accepting a guard-committed
    TOOL_EXECUTION_COMPLETED through index_event raised the Event-derived
    adapter's forbidden upsert before projections were saved, leaving the
    event store ahead of the projection row and wedging the session.
    """
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Fenced accept",
            user_input="continue",
            workspace_root=Path("/tmp/fenced-accept"),
        )
    )
    workspace = rebuild_workspace(list(bootstrap.events))
    model_store = Mock()
    model_store.index_worker_event.return_value = None
    tool_store = Mock()
    tool_store.index_worker_event.return_value = None

    def _forbidden_upsert(record):  # noqa: ANN001
        raise AssertionError("legacy upsert must not be used on cloud recorders")

    model_store.upsert.side_effect = _forbidden_upsert
    tool_store.upsert.side_effect = _forbidden_upsert
    event_store = Mock()
    event_store.read_since.return_value = []
    projection_store = Mock()
    workspace_store = Mock()
    transaction = Mock()
    authority = WorkerMutationAuthority(
        deployment_namespace="cloud-a",
        session_id=bootstrap.session.session_id,
        lease_fence=LeaseFence(
            control_plane_epoch=uuid4(),
            fencing_token=9,
            owner_instance_id="worker-a",
        ),
        expected_stream_revision=bootstrap.session.current_sequence,
    )
    recorder = DurableHarnessEventRecorder(
        session=bootstrap.session,
        workspace=workspace,
        event_store=event_store,
        projection_store=projection_store,
        workspace_store=workspace_store,
        model_call_indexer=ModelCallIndexer(model_store),
        tool_run_indexer=ToolRunIndexer(tool_store, None),
        worker_projection_transaction=transaction,
        worker_mutation_authority=authority,
    )
    completed = SessionEvent.create(
        session_id=bootstrap.session.session_id,
        sequence=bootstrap.session.current_sequence + 1,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "tool_name": "command.run",
            "tool_call_id": str(uuid4()),
            "status": "executed",
            "output": "effect-e2e-proof",
            "metadata": {},
        },
        created_at=datetime(2026, 8, 15, 0, 0, tzinfo=UTC),
    )

    accepted = recorder.accept_persisted_event(completed)

    assert accepted == completed
    model_store.upsert.assert_not_called()
    tool_store.upsert.assert_not_called()
    tool_store.index_worker_event.assert_called_once_with(completed, authority=authority)
    transaction.commit_worker_event.assert_not_called()
    saved_session = projection_store.save_session.call_args.args[0]
    assert saved_session.current_sequence == completed.sequence
    workspace_store.save_workspace.assert_called_once()
    assert recorder.session.current_sequence == completed.sequence
