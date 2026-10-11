from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.leases import LeaseLostError, WorkerLease
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_output import PublicOutputPolicy
from agent_core.ports import WorkerMutationAuthority, WorkerProjectionCommitResult
from agent_storage import SQLiteArtifactPayloadStore
from zebra_agent_worker.effect_runtime import guard_worker_effects
from zebra_agent_worker.execution_context import (
    HOST_EMBEDDED_AGENT_IDENTITY_DIRECTIVE,
    build_worker_orchestrator,
)
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.progress_recovery import recover_worker_progress

from tests.agent_core.test_public_output import verified_facts
from tests.agent_tools.test_effect_guard import _call, _Dispatch, _fence, _Gateway
from tests.worker.test_recorder_append_guards import _recorder


def test_cloud_progress_guidance_uses_existing_tool_response() -> None:
    from agent_core.harness import HarnessModelStep, HarnessTask

    task = HarnessTask(title="Read", user_input="Query my sources.",
                       identity_directive=HOST_EMBEDDED_AGENT_IDENTITY_DIRECTIVE)
    messages = HarnessModelStep().build_initial_messages(
        task, created_at=datetime(2026, 10, 7, tzinfo=UTC)
    )
    assert "in assistant content alongside tool calls" in messages[0].content
    assert "do not add a separate model call" in messages[0].content
    assert "meaningful received evidence" in messages[0].content
    assert "never private chain-of-thought" in messages[0].content


def _progress(stores, recorder):
    session_id = recorder.session.session_id
    task = stores.tasks.ensure_for_session(session_id)
    while not stores.tasks.backfill_event_positions(task.task_id):
        pass
    while not stores.tasks.backfill_replay_headers(task.task_id):
        pass
    command = SessionCommand(
        session_id=session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=recorder.session.current_sequence,
        idempotency_key="progressive:run",
        payload={"run_id": "progressive:run"},
    )
    recorder.append(EventType.SESSION_COMMAND_ACCEPTED, EventActor.USER, command.event_payload())
    return recover_worker_progress(
        tasks=stores.tasks,
        namespace="local",
        session_id=session_id,
        ownership_check=lambda: None,
    )


def test_recovery_keeps_task_policy_not_current_environment(tmp_path, monkeypatch) -> None:
    stores, recorder, session_id = _recorder(tmp_path)
    recovery = _progress(stores, recorder)
    persisted = []
    frozen = PublicOutputPolicy(version="original", wait_seconds=30, delta_seconds=0.05)
    recorder.append(EventType.HARNESS_ATTEMPT_STARTED, EventActor.HARNESS, {"attempt_number": 3})
    recorder.append(
        EventType.MODEL_REQUEST_STARTED,
        EventActor.HARNESS,
        {"model_call_id": "original", "public_output_policy": asdict(frozen)},
    )

    def persist(draft):
        recorder.append_draft(draft)
        persisted.append(draft)

    monkeypatch.setattr(
        "zebra_agent_worker.execution_context.provider_runtime.build_worker_context_sinks",
        lambda *_args, **_kwargs: (persist, None),
    )
    monkeypatch.setattr(
        stores.events, "list_for_session", lambda _: pytest.fail("full history read")
    )
    tools = SimpleNamespace(
        model_tools=(),
        parallel_safe_tools=frozenset(),
        parallel_batch_limits={},
        resolve_model_tool_calls=lambda calls: calls,
    )
    orchestrator = build_worker_orchestrator(
        model_gateway=object(),
        policy_engine=object(),
        tool_gateway=tools,
        context_compiler=object(),
        cloud_continuation=None,
        recorder=SimpleNamespace(
            worker_mutation_authority=SimpleNamespace(deployment_namespace="local")
        ),
        event_store=stores.events,
        lifecycle_store=None,
        cloud_artifacts=None,
        local_continuation_store=None,
        session_id=session_id,
        provider_continuation=None,
        public_output_policy=PublicOutputPolicy(version="changed", wait_seconds=5),
        worker_progress=recovery,
        user_input="Summarize my sources",
        attempt_number=3,
    )
    try:
        orchestrator._event_sink(
            HarnessEventDraft(
                EventType.MODEL_REQUEST_STARTED,
                EventActor.HARNESS,
                {"model_call_id": "next"},
            )
        )
        assert persisted[-1].payload["public_output_policy"] == asdict(frozen)
        assert recovery.head.state.attempt_number == 3
    finally:
        orchestrator.close()


@pytest.mark.parametrize(
    "outcome", ["success", "rejected", "uncertain", "raised", "commit_error", "callback_lease_loss"]
)
def test_each_drained_effect_finishes_shared_progress_outside_mutation(
    tmp_path, monkeypatch, outcome
) -> None:
    stores, local_recorder, session_id = _recorder(tmp_path)
    recovery = _progress(stores, local_recorder)
    fence = _fence()
    owned = True

    def require_owned():
        if not owned:
            raise LeaseLostError("observer lost lease")

    def commit(event, session, workspace, *, authority):
        require_owned()
        assert authority.lease_fence == fence
        assert authority.expected_stream_revision == event.sequence - 1
        stores.events.append(event)
        return WorkerProjectionCommitResult(event=event, session=session, workspace=workspace)

    transaction = Mock()
    transaction.commit_worker_event.side_effect = commit
    transaction.project_persisted_worker_event.side_effect = (
        lambda event, session, workspace, **_: WorkerProjectionCommitResult(
            event=event, session=session, workspace=workspace
        )
    )
    recorder = DurableHarnessEventRecorder(
        session=local_recorder.session,
        workspace=local_recorder.workspace,
        event_store=stores.events,
        projection_store=stores.sessions,
        workspace_store=stores.workspaces,
        model_call_indexer=Mock(),
        tool_run_indexer=Mock(),
        ownership_check=require_owned,
        worker_projection_transaction=transaction,
        worker_mutation_authority=WorkerMutationAuthority(
            deployment_namespace="local",
            session_id=session_id,
            lease_fence=fence,
            expected_stream_revision=local_recorder.session.current_sequence,
        ),
    )

    class PendingDispatch(_Dispatch):
        def __init__(self):
            super().__init__()
            self.queue = []

        def schedule(self, request, *, fence):
            scheduled = super().schedule(request, fence=fence)
            self.queue.append(scheduled)
            self.pending = None
            stores.events.append(request.started_event)
            return scheduled

        def claim_next(self, session_id, *, fence, claim_ttl):
            self.pending = self.queue.pop(0)
            return super().claim_next(session_id, fence=fence, claim_ttl=claim_ttl)

        def complete(self, claim, *, result, terminal_event):
            if outcome == "commit_error" and result.tool_call_id == calls[1].tool_call_id:
                raise RuntimeError("terminal commit failed")
            return stores.events.append(terminal_event)

        def fail_no_effect(self, claim, *, evidence, terminal_event):
            super().fail_no_effect(claim, evidence=evidence, terminal_event=terminal_event)
            return stores.events.append(terminal_event)

        def mark_uncertain(self, claim, *, evidence, terminal_event):
            super().mark_uncertain(claim, evidence=evidence, terminal_event=terminal_event)
            return stores.events.append(terminal_event)

    calls = [_call("command.run").model_copy(update={"arguments": {"index": i}}) for i in range(3)]
    gateway = _Gateway()
    dispatch = PendingDispatch()
    now = datetime.now(UTC)
    guarded = guard_worker_effects(
        gateway,
        ledger=None,
        session_id=session_id,
        recovered_handoff=None,
        authority_scope="workspace-write",
        dispatch=dispatch,
        local_artifacts=SQLiteArtifactPayloadStore(tmp_path / "effects.sqlite"),
        lease=WorkerLease(
            session_id=session_id,
            fence=fence,
            checkpoint=recorder.session.current_sequence,
            acquired_at=now,
            heartbeat_at=now,
            expires_at=now + timedelta(seconds=30),
        ),
        recorders=[recorder],
        ownership_check=require_owned,
        cloud_artifacts=None,
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution_context.provider_runtime.build_worker_context_sinks",
        lambda *_args, **_kwargs: (recorder.append_draft, None),
    )
    orchestrator = build_worker_orchestrator(
        model_gateway=object(),
        policy_engine=object(),
        tool_gateway=guarded,
        context_compiler=object(),
        cloud_continuation=None,
        recorder=recorder,
        event_store=stores.events,
        lifecycle_store=None,
        cloud_artifacts=None,
        local_continuation_store=None,
        session_id=session_id,
        provider_continuation=None,
        public_output_policy=PublicOutputPolicy(wait_seconds=300),
        worker_progress=recovery,
        user_input="Do the work",
    )
    progress = orchestrator._event_sink
    active_at_dispatch = []
    terminal_observations = []
    observe = progress._observe

    def observe_terminal(event):
        if event.event_type in {
            EventType.TOOL_EXECUTION_COMPLETED,
            EventType.TOOL_EXECUTION_FAILED,
        }:
            assert not recorder._mutation_lock._is_owned()
            terminal_observations.append(event.payload["tool_call_id"])
        observe(event)

    monkeypatch.setattr(progress, "_observe", observe_terminal)
    start = recorder.effect_started_listener

    def started(call_id):
        nonlocal owned
        start(call_id)
        if outcome == "callback_lease_loss" and call_id == str(calls[1].tool_call_id):
            owned = False

    recorder.effect_started_listener = started

    def execute(call):
        assert not recorder._mutation_lock._is_owned()
        gateway.calls += 1
        active_at_dispatch.append(set(progress._active))
        if call.tool_call_id == calls[1].tool_call_id:
            if outcome == "raised":
                raise TimeoutError("provider outcome unknown")
            if outcome in {"rejected", "uncertain"}:
                return ToolResult(
                    tool_call_id=call.tool_call_id,
                    status=ToolCallStatus.FAILED,
                    metadata=(
                        {"transport_outcome": "returned", "business_outcome": "rejected"}
                        if outcome == "rejected"
                        else {"transport_outcome": "timed_out", "business_outcome": "unknown"}
                    ),
                )
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="ok",
            metadata={
                "public_facts": verified_facts(f"Confirmed result {call.arguments['index']}")
            },
        )

    monkeypatch.setattr(gateway, "execute", execute)
    try:
        for old_call in calls[:2]:
            with recorder.mutation():
                guarded._schedule(old_call)
        if outcome in {"raised", "commit_error", "callback_lease_loss"}:
            error, message = {
                "raised": (TimeoutError, "provider outcome unknown"),
                "commit_error": (RuntimeError, "terminal commit failed"),
                "callback_lease_loss": (LeaseLostError, "observer lost lease"),
            }[outcome]
            with pytest.raises(error, match=message):
                guarded.execute(calls[2])
            claimed_count = 2
        else:
            assert guarded.execute(calls[2]).status is ToolCallStatus.EXECUTED
            claimed_count = 3
        assert progress._active == set()
        assert progress._timer is None
        assert terminal_observations == [str(call.tool_call_id) for call in calls[:claimed_count]]
        dispatched_count = claimed_count - (outcome == "callback_lease_loss")
        assert gateway.calls == dispatched_count
        assert active_at_dispatch == [
            {f"tool:{call.tool_call_id}"} for call in calls[:dispatched_count]
        ]
        assert dispatch.uncertain == int(outcome in {"uncertain", "raised"})
        assert dispatch.failed_no_effect == int(outcome == "rejected")
        events = stores.events.list_for_session(session_id)
        started_ids = [
            event.payload["tool_call_id"]
            for event in events
            if event.event_type is EventType.TOOL_EXECUTION_STARTED
        ]
        terminal_ids = [
            event.payload["tool_call_id"]
            for event in events
            if event.event_type
            in {
                EventType.TOOL_EXECUTION_COMPLETED,
                EventType.TOOL_EXECUTION_FAILED,
            }
        ]
        assert started_ids == [str(call.tool_call_id) for call in calls]
        durable_count = claimed_count - (outcome in {"commit_error", "callback_lease_loss"})
        assert terminal_ids == [str(call.tool_call_id) for call in calls[:durable_count]]
        assert [event.sequence for event in events] == list(range(len(events)))
        evidence_outputs = [
            event.payload
            for event in events
            if event.event_type is EventType.PUBLIC_OUTPUT and event.payload["phase"] == "evidence"
        ]
        assert any(
            output["evidence_refs"] == [str(calls[0].tool_call_id)]
            and output["content"] == "Confirmed result 0"
            and output["meaningful"]
            for output in evidence_outputs
        )
        if outcome == "commit_error":
            assert all(
                str(calls[1].tool_call_id) not in out["evidence_refs"] for out in evidence_outputs
            )
        waiting_before = sum(event.payload.get("phase") == "waiting" for event in events)
        progress._wait_elapsed(progress._timer_generation)
        assert (
            sum(
                event.payload.get("phase") == "waiting"
                for event in stores.events.list_for_session(session_id)
            )
            == waiting_before
        )
    finally:
        orchestrator.close()
