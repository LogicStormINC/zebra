"""Exercise the Worker entry, not just the progressive-output builder."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.leases import LeaseFence, LeaseLostError, WorkerLease
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult, HarnessEventDraft
from agent_core.harness.public_output import PublicOutputPolicy
from agent_core.ports import WorkerMutationAuthority, WorkerProjectionCommitResult
from agent_core.ports.worker_preparation import PreparationAdvanced
from agent_security.network_profile import parse_network_profile
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.execution import SessionExecutionService
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_finalization import RetryableWorkerSetupError
from zebra_agent_worker.recovery import RecoveredSession

from tests.worker.execution.worker_execution_support import _settings
from tests.worker.test_progressive_composition import _progress
from tests.worker.test_recorder_append_guards import _recorder


def _entry(tmp_path, monkeypatch, *, admitted=True):
    stores, original, session_id = _recorder(tmp_path)
    if admitted:
        _progress(stores, original)
        original.append(
            EventType.HARNESS_ATTEMPT_STARTED, EventActor.HARNESS, {"attempt_number": 3}
        )
        original.append(
            EventType.MODEL_REQUEST_STARTED,
            EventActor.HARNESS,
            {
                "model_call_id": "first",
                "attempt_number": 3,
                "public_output_policy": asdict(PublicOutputPolicy(version="frozen")),
            },
        )
    now = datetime.now(UTC)
    lease = WorkerLease(
        session_id=session_id,
        fence=LeaseFence(
            control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="progress-entry"
        ),
        checkpoint=original.session.current_sequence,
        acquired_at=now,
        heartbeat_at=now,
        expires_at=now + timedelta(seconds=30),
    )
    claimed = ClaimedSession(
        RecoveredSession(
            original.session,
            original.workspace,
            original.next_sequence,
            original.session.current_sequence,
            False,
        ),
        lease,
    )
    transaction = Mock()

    def commit(event, session, workspace, *, authority):
        assert authority.deployment_namespace == "local" and authority.lease_fence == lease.fence
        assert authority.expected_stream_revision == event.sequence - 1
        canonical = stores.events.append(event)
        stores.sessions.save_session(session)
        stores.workspaces.save_workspace(workspace)
        return WorkerProjectionCommitResult(event=canonical, session=session, workspace=workspace)

    transaction.commit_worker_event.side_effect = commit
    recorder = DurableHarnessEventRecorder(
        session=original.session,
        workspace=original.workspace,
        event_store=stores.events,
        projection_store=stores.sessions,
        workspace_store=stores.workspaces,
        model_call_indexer=Mock(),
        tool_run_indexer=Mock(),
        worker_projection_transaction=transaction,
        worker_mutation_authority=WorkerMutationAuthority(
            deployment_namespace="local",
            session_id=session_id,
            lease_fence=lease.fence,
            expected_stream_revision=original.session.current_sequence,
        ),
    )
    task = SimpleNamespace(
        user_input="请核对我的订阅来源",
        title="核对来源",
        workspace_root=tmp_path,
        policy_profile="read_only",
        network_profile=parse_network_profile("none"),
        model_invocation_policy=None,
        coverage_admission=None,
        interaction_mode=Mock(),
    )
    settings = _settings(tmp_path / "recorder.sqlite")
    factory = SimpleNamespace(build=lambda **_: recorder)
    service = SimpleNamespace(
        _execution_namespace="local",
        _coverage_runtime=None,
        _transient_output_factory=None,
        _execution_input_store=None,
        _task_index_store=stores.tasks,
        _event_store=stores.events,
        _cloud_artifact_factory=None,
        _settings=settings,
        _projection_recorder_factory=factory,
        _cloud_provider_continuation_factory=None,
        _provider_continuation_store=None,
        _control_service=None,
        _recovery_service=None,
        _context_lifecycle_store=None,
        _handoff_gate=None,
        _artifact_payload_reader=None,
        _workspace_resolver=None,
        _artifact_payload_store=object(),
        _context_materialization_store=None,
        _task_binding_loader=None,
        _execution_authority_resolver=None,
        _execution_authority_scope=None,
        _execution_authority_scope_provider=None,
        _extensions=SimpleNamespace(snapshot_store=None, mcp=None),
        _runtime_instance_factory=None,
        _database_path=tmp_path / "recorder.sqlite",
        _effect_ledger=None,
        _effect_dispatch=None,
        _memory_store=None,
        _personalization_store=None,
        _delegation_store=None,
        _projection_store=stores.sessions,
        _workspace_store=stores.workspaces,
        _memory_extraction_service=None,
        _memory_promotion_service=None,
        _cloud_memory_store=None,
        _deployment_namespace="local",
    )
    gateway = SimpleNamespace(
        model_tools=(),
        parallel_safe_tools=frozenset(),
        parallel_batch_limits={},
        resolve_model_tool_calls=lambda calls: calls,
        read_only_tools=frozenset(),
        authorized_write_tools=frozenset(),
        approval_required_tools=frozenset(),
        close=Mock(),
    )
    model = Mock()
    monkeypatch.setattr("zebra_agent_worker.execution.execution_gateway.model_gateway", model)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.recover_execution_inputs",
        lambda **_: SimpleNamespace(
            claimed=claimed,
            session_events=stores.events.list_for_session(session_id),
            provider_continuation=None,
            cloud_continuation=None,
            task=task,
            active_capsule=None,
            recovered_handoff=None,
            execution_input_reader=None,
        ),
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.prepare_worker_context",
        lambda **kw: SimpleNamespace(
            claimed=kw["claimed"],
            events=kw["events"],
            binding=None,
            materialization=None,
            extension=None,
        ),
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.runtime_setup.runtime_session_ids", lambda *_: ()
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.runtime_setup.bind_instance_factory", lambda *_: None
    )
    provision = Mock(
        return_value=(Mock(), SimpleNamespace(handle=Mock(), compatible_authority_digests=()))
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.runtime_setup.build_prepared_runtime", provision
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.runtime_setup.require_matching_runtime_authority",
        lambda *_: None,
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.runtime_authority.persist_runtime_authority",
        lambda *_, **__: False,
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.execution_gateway.build_execution_tool_gateway",
        lambda *_, **__: gateway,
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.guard_worker_effects", lambda value, **_: value
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.execution_context.harness_task_for_recovered",
        lambda *_, **__: Mock(),
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution_context.provider_runtime.build_worker_context_sinks",
        lambda *_, **__: (recorder.append_draft, None),
    )
    finished = Mock(return_value="finished")
    monkeypatch.setattr("zebra_agent_worker.execution.finish_execution", finished)
    return service, claimed, stores, recorder, model, provision, gateway, finished


def test_worker_entry_restores_attempt_language_and_frozen_policy(tmp_path, monkeypatch):
    service, claimed, stores, recorder, _, provision, gateway, finished = _entry(
        tmp_path, monkeypatch
    )
    composition = Mock(return_value=gateway)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.execution_gateway.build_execution_tool_gateway", composition
    )

    def run(orchestrator, context, **_):
        assert context.attempt.number == 3
        try:
            orchestrator._event_sink(
                HarnessEventDraft(
                    EventType.MODEL_REQUEST_STARTED,
                    EventActor.HARNESS,
                    {"model_call_id": "next", "attempt_number": 3},
                )
            )
            orchestrator._event_sink(
                HarnessEventDraft(
                    EventType.TOOL_CALL_PROPOSED,
                    EventActor.HARNESS,
                    {"tool_call_id": "read:1", "tool_name": "source.read"},
                )
            )
            return HarnessAttemptResult(HarnessAttemptOutcome.COMPLETED, "Verified")
        finally:
            orchestrator.close()

    monkeypatch.setattr("zebra_agent_worker.execution_completion.run_continuation", run)
    assert (
        SessionExecutionService._execute_claimed_session_once(
            service, claimed, started_at=datetime.now(UTC), ownership_check=lambda: None
        )
        == "finished"
    )
    events = stores.events.list_for_session(recorder.session.session_id)
    requests = [event for event in events if event.event_type is EventType.MODEL_REQUEST_STARTED]
    outputs = [event for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
    assert requests[-1].payload["public_output_policy"]["version"] == "frozen"
    assert outputs and outputs[0].payload["attempt_number"] == 3
    assert any("\u4e00" <= char <= "\u9fff" for char in outputs[0].payload["content"])
    assert (
        len([event for event in events if event.event_type is EventType.HARNESS_ATTEMPT_STARTED])
        == 1
    )
    assert (
        provision.call_args.kwargs["attempt_number"]
        == finished.call_args.kwargs["attempt_number"]
        == composition.call_args.kwargs["attempt_number"]
        == 3
    )
    gateway.close.assert_called_once()


@pytest.mark.parametrize("cause", ["missing_run", "lost_lease"])
def test_worker_entry_rejects_unprepared_or_lost_authority_before_model_and_runtime(
    tmp_path, monkeypatch, cause
):
    service, claimed, stores, _, model, provision, _, finished = _entry(
        tmp_path, monkeypatch, admitted=cause != "missing_run"
    )
    before = stores.events.list_for_session(claimed.lease.session_id)

    def ownership():
        if cause == "lost_lease":
            raise LeaseLostError("lease lost")

    with pytest.raises(RetryableWorkerSetupError if cause == "missing_run" else LeaseLostError):
        SessionExecutionService._execute_claimed_session_once(
            service, claimed, started_at=datetime.now(UTC), ownership_check=ownership
        )
    model.assert_not_called()
    provision.assert_not_called()
    finished.assert_not_called()
    assert stores.events.list_for_session(claimed.lease.session_id) == before


def test_worker_preparation_does_not_reenter_model_or_provision_between_slices(
    tmp_path, monkeypatch
):
    service, claimed, _, _, model, provision, _, finished = _entry(tmp_path, monkeypatch)
    from zebra_agent_worker import execution

    original = execution.recover_execution_progress
    slices = 0

    def recover(*args):
        nonlocal slices
        slices += 1
        if slices < 3:
            model.assert_not_called()
            provision.assert_not_called()
            finished.assert_not_called()
            raise PreparationAdvanced("progress-entry", slices * 256, 1000)
        return original(*args)

    monkeypatch.setattr(execution, "recover_execution_progress", recover)
    assert (
        SessionExecutionService._execute_claimed_session_once(
            service, claimed, started_at=datetime.now(UTC), ownership_check=lambda: None
        )
        == "finished"
    )
    assert slices == 3
    provision.assert_called_once()
    finished.assert_called_once()
