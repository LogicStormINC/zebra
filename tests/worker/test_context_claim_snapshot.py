"""A fenced append already committed its projections; recovery is not another write."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.leases import LeaseFence, LeaseLostError, WorkerLease
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from zebra_agent_worker import context_materialization as context
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.recovery import RecoveredSession


def inputs():
    now = datetime.now(UTC)
    initial = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="context",
            user_input="hello",
            workspace_root=Path("/tmp"),
            created_at=now,
        )
    )
    old = RecoveredSession(initial.session, rebuild_workspace(initial.events), 3, 2, False)
    lease = WorkerLease(
        session_id=initial.session.session_id,
        fence=LeaseFence(control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="worker"),
        acquired_at=now,
        heartbeat_at=now,
        expires_at=now + timedelta(seconds=30),
    )
    session = old.session.model_copy(update={"current_sequence": old.last_sequence + 1})
    workspace = old.workspace.model_copy(update={"current_sequence": session.current_sequence})
    authority = WorkerMutationAuthority(
        deployment_namespace="cloud",
        session_id=session.session_id,
        lease_fence=lease.fence,
        expected_stream_revision=session.current_sequence,
    )
    recorder = SimpleNamespace(
        session=session,
        workspace=workspace,
        worker_mutation_authority=authority,
        read_active_session=Mock(return_value=session),
        mutation=lambda: nullcontext(),
    )
    return ClaimedSession(old, lease), recorder


def test_committed_cloud_projection_is_reused_after_fresh_control_check():
    claimed, recorder = inputs()
    recovery = Mock()
    refreshed = context._refresh_claim(recorder, recovery, claimed, Mock())
    recovery.recover_session.assert_not_called()
    recorder.read_active_session.assert_called_once_with()
    assert refreshed.lease == claimed.lease
    assert refreshed.recovery.session is recorder.session
    assert refreshed.recovery.workspace is recorder.workspace
    assert refreshed.recovery.last_sequence == recorder.session.current_sequence
    assert refreshed.recovery.event_count == recorder.session.current_sequence + 1
    assert not refreshed.recovery.is_terminal
    # Immutable old claim is not silently mutated.
    assert claimed.recovery.session.current_sequence < recorder.session.current_sequence


@pytest.mark.parametrize("kind", ["cancel", "lease"])
def test_fresh_control_or_ownership_rejection_prevents_snapshot(kind):
    claimed, recorder = inputs()
    failure = ExecutionInterrupted("cancelled") if kind == "cancel" else LeaseLostError("expired")
    recorder.read_active_session.side_effect = failure
    with pytest.raises(type(failure)):
        context._refresh_claim(recorder, Mock(), claimed, Mock())


@pytest.mark.parametrize("kind", ["session", "fence", "revision", "workspace"])
def test_foreign_or_incoherent_committed_projection_fails_closed(kind):
    claimed, recorder = inputs()
    authority = recorder.worker_mutation_authority
    if kind == "workspace":
        recorder.workspace = recorder.workspace.model_copy(update={"current_sequence": -1})
    elif kind == "fence":
        recorder.worker_mutation_authority = authority.model_copy(
            update={
                "lease_fence": authority.lease_fence.model_copy(update={"fencing_token": 2}),
            }
        )
    else:
        field, value = (
            ("session_id", uuid4()) if kind == "session" else ("expected_stream_revision", -1)
        )
        recorder.worker_mutation_authority = authority.model_copy(update={field: value})
    with pytest.raises(LeaseLostError):
        context._refresh_claim(recorder, Mock(), claimed, Mock())


def test_local_claim_keeps_existing_recovery_path():
    claimed, recorder = inputs()
    recorder.worker_mutation_authority = None
    recovery = Mock()
    recovery.recover_session.return_value = replace(claimed.recovery, is_terminal=True)
    ownership = Mock()
    refreshed = context._refresh_claim(recorder, recovery, claimed, ownership)
    recovery.recover_session.assert_called_once_with(
        claimed.lease.session_id, worker_lease=claimed.lease
    )
    ownership.assert_called_once_with()
    recorder.read_active_session.assert_not_called()
    assert refreshed.recovery.is_terminal


def test_fresh_cloud_control_read_keeps_native_two_second_deadline():
    from time import monotonic

    from agent_storage.postgres.task_io import current_task_io_deadline

    claimed, recorder = inputs()

    def check():
        deadline = current_task_io_deadline()
        assert deadline is not None and 0 < deadline - monotonic() <= 2

    recorder.read_active_session.side_effect = check
    context._refresh_claim(recorder, Mock(), claimed, Mock())
    assert current_task_io_deadline() is None


def test_explicit_ownership_check_is_retained_for_cloud_snapshot():
    claimed, recorder = inputs()
    ownership = Mock(side_effect=LeaseLostError("caller ownership lost"))
    with pytest.raises(LeaseLostError):
        context._refresh_claim(recorder, Mock(), claimed, ownership)
    recorder.read_active_session.assert_not_called()


def test_concurrent_primary_change_keeps_original_bounded_recovery():
    claimed, recorder = inputs()
    recorder.read_active_session.return_value = recorder.session.model_copy(
        update={"current_sequence": recorder.session.current_sequence + 1}
    )
    recovery = Mock()
    refreshed = context._refresh_claim(recorder, recovery, claimed, Mock())
    recovery.recover_session.assert_called_once_with(
        claimed.lease.session_id, worker_lease=claimed.lease
    )
    assert refreshed.recovery is recovery.recover_session.return_value


def test_active_execution_returns_the_fresh_primary_projection(tmp_path):
    from tests.worker.test_recorder_append_guards import _recorder

    stores, recorder, session_id = _recorder(tmp_path)
    assert recorder.read_active_session() == stores.sessions.get_session(session_id)
    assert recorder.require_active_execution() is None
