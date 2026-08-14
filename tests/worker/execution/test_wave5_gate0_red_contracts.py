"""Wave 5 Gate 0 red/contract tests (ZNX-WAVE5-OUTER-ATTEMPTS-01).

These tests encode the Wave 5 contracts registered in
``docs/znx-wave5-existing-state-audit-2026-08-14.md`` and MUST FAIL at the
exact base ``1d19abb``. They prove the real Hosted Worker gaps; no production
code is changed to make them green. Phase 1+ implements the contracts.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_core.application import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts.events import event_payload_schema_for
from agent_core.domain.agent_tasks import AgentTask
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessLoop,
    HarnessStoppingPolicy,
    HarnessTask,
    StepClock,
)
from agent_storage import (
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from worker_execution_support import (
    _assistant_only_gateway,
    _build_execution_service,
    _created_at,
)
from zebra_agent_api.task_final_identity import final_message_identity
from zebra_agent_worker import SessionClaimService, SessionRecoveryService
from zebra_agent_worker.resume import SessionResumeService


def _created_at_plus(seconds: int) -> datetime:
    return _created_at() + timedelta(seconds=seconds)


def _seed_session(
    database_path: Path,
    workspace_root: Path,
    *,
    max_attempts: int = 1,
):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Queued worker task",
            user_input="Continue the queued task.",
            workspace_root=workspace_root.resolve(),
            tool_profile=ToolProfile.CODING,
            max_attempts=max_attempts,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SessionRecoveryService(
        event_store,
        SQLiteProjectionStore(database_path),
        SQLiteWorkspaceProjectionStore(database_path),
    ).recover_session(bootstrap.session.session_id)
    return bootstrap


class _ExplodingGateway:
    """Provider that fails deterministically with a generic transport error."""

    def complete(self, messages, *, tools=()):
        raise RuntimeError("provider transport exploded")

    def complete_stream(self, messages, *, tools=(), on_text_delta=None):
        raise RuntimeError("provider transport exploded")


# R1: Hosted Worker must start Attempt 2 after a retryable attempt-1 failure.
def test_r1_hosted_worker_starts_attempt_2_after_retryable_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "wave5-r1.db"
    bootstrap = _seed_session(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _ExplodingGateway(),
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="wave5-red-r1",
        executed_at=_created_at(),
    )

    events = SQLiteEventStore(database_path).list_for_session(session_id)
    attempt_started = [
        event for event in events if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    failed = next(event for event in events if event.event_type is EventType.SESSION_FAILED)
    assert [event.payload["attempt_number"] for event in attempt_started] == [1, 2]
    assert failed.payload["attempt_number"] == 2


# R2: evidence-correction failure is retryable when attempts remain, and the
# outer loop must start Attempt 2 instead of terminal-failing.
def test_r2_evidence_correction_failure_is_retryable_when_attempts_remain() -> None:
    policy = HarnessStoppingPolicy()
    attempt_result = HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="evidence still missing after bounded correction",
        metadata={"stop_reason": "completion_evidence_missing"},
    )

    assert (
        policy.should_retry(
            max_attempts=2,
            max_model_calls=None,
            max_tool_calls=None,
            attempts_used=1,
            model_calls_used=1,
            tool_calls_used=0,
            attempt_result=attempt_result,
        )
        is True
    )


def test_r2_harness_loop_starts_attempt_2_after_evidence_correction_failure() -> None:
    loop = HarnessLoop(
        clock=StepClock(
            current=datetime(2026, 8, 14, 1, 0, tzinfo=UTC),
            step=timedelta(seconds=1),
        )
    )
    task = HarnessTask(
        title="Evidence retry",
        user_input="prove the evidence contract",
        max_attempts=2,
    )

    result = loop.run(
        task,
        lambda _context: HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.FAILED,
            summary="evidence still missing after bounded correction",
            metadata={"stop_reason": "completion_evidence_missing"},
        ),
    )

    assert len(result.attempt_results) == 2
    assert result.run_result.attempts_used == 2


# R3: a retryable-failed session must be resumable as Attempt 2.
def test_r3_retryable_failed_session_resumes_as_attempt_2(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "wave5-r3.db"
    bootstrap = _seed_session(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _ExplodingGateway(),
    )
    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="wave5-red-r3",
        executed_at=_created_at(),
    )
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
            SQLiteWorkspaceProjectionStore(database_path),
        ),
    )

    resumed = SessionResumeService(claim_service).resume_session(
        session_id,
        worker_id="wave5-red-r3-resume",
        resumed_at=_created_at_plus(60),
        lease_ttl_seconds=30,
    )

    assert resumed.claimed is not None


# R4 (W5-DSH-02): HARNESS_ATTEMPT_STARTED must have a durable coordinates
# payload contract.
def test_r4_attempt_started_payload_contract_carries_durable_coordinates() -> None:
    schema = event_payload_schema_for(EventType.HARNESS_ATTEMPT_STARTED)
    properties = schema["properties"]
    for field in (
        "attempt_id",
        "attempt_sequence",
        "started_at",
        "ended_at",
        "terminal_reason",
        "causal_attempt_id",
    ):
        assert field in properties


# R5 (W5-DSH-01): every model dispatch records the private reconstruction
# coordinates and accepts them in the durable payload contract.
def test_r5_model_request_payload_carries_reconstruction_coordinates() -> None:
    schema = event_payload_schema_for(EventType.MODEL_REQUEST_STARTED)
    properties = schema["properties"]
    for field in (
        "stable_task_id",
        "attempt_id",
        "turn_id",
        "step_id",
        "goal_revision",
        "plan_revision",
        "resource_manifest_digest",
        "messages_digest",
        "system_prompt_digest",
        "tool_schema_digest",
        "model_config_digest",
    ):
        assert field in properties

    SessionEvent.create(
        session_id=new_session_id(),
        sequence=3,
        event_type=EventType.MODEL_REQUEST_STARTED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "model_call_id": "call-1",
            "stable_task_id": "task-1",
            "attempt_id": "attempt-1",
            "turn_id": "turn-1",
            "step_id": "step-1",
            "goal_revision": 1,
            "plan_revision": 1,
            "resource_manifest_digest": "sha256:" + "a" * 64,
            "messages_digest": "sha256:" + "b" * 64,
            "system_prompt_digest": "sha256:" + "c" * 64,
            "tool_schema_digest": "sha256:" + "d" * 64,
            "model_config_digest": "sha256:" + "e" * 64,
        },
        created_at=_created_at(),
    )


# R6: the Task terminal event must carry a coverage verdict.
def test_r6_task_terminal_carries_coverage_verdict(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "wave5-r6.db"
    bootstrap = _seed_session(database_path, tmp_path, max_attempts=1)
    session_id = bootstrap.session.session_id
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="wave5-red-r6",
        executed_at=_created_at(),
    )
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    completed = next(event for event in events if event.event_type is EventType.SESSION_COMPLETED)
    verdict = completed.payload.get("coverage_verdict")
    assert verdict is not None
    assert verdict["status"] in {"complete", "partial", "missing"}


# R7: a failed attempt's candidate final must stay attempt-private; it must
# not become the public canonical final or the final identity.
def test_r7_failed_attempt_candidate_final_stays_out_of_public_canonical_final(
    tmp_path: Path,
) -> None:
    from agent_core.application.public_conversation import (
        project_public_conversation,
    )

    database_path = tmp_path / "wave5-r7.db"
    bootstrap = _seed_session(database_path, tmp_path, max_attempts=2)
    session = bootstrap.session
    event_store = SQLiteEventStore(database_path)
    additions = (
        SessionEvent.create(
            session_id=session.session_id,
            sequence=3,
            event_type=EventType.MODEL_REQUEST_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1, "model_call_id": "call-1"},
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session.session_id,
            sequence=4,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "model_call_id": "call-1",
                "assistant_message": "attempt-1 candidate final",
                "response_stage": "final",
            },
            created_at=_created_at_plus(1),
        ),
        SessionEvent.create(
            session_id=session.session_id,
            sequence=5,
            event_type=EventType.SESSION_FAILED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "summary": "coverage still missing",
                "metadata": {"stop_reason": "completion_evidence_missing"},
            },
            created_at=_created_at_plus(2),
        ),
    )
    for event in additions:
        event_store.append(event)
    projected_session = session
    for event in additions:
        projected_session = apply_event(projected_session, event)
    SQLiteProjectionStore(database_path).save_session(projected_session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        rebuild_workspace((*bootstrap.events, *additions))
    )
    task_store = SQLiteAgentTaskStore(database_path)
    task = task_store.ensure_for_session(session.session_id)
    task_events = task_store.read_events(task.task_id, -1)

    projection = project_public_conversation(task.task_id, task_events)
    final_items = [item for item in projection.items if item.role == "final_response"]
    assert final_items == []
    assert any(item.role == "failure" for item in projection.items)
    assert final_message_identity(database_path, str(task.task_id)) is None


# R8: attempt usage must be aggregatable into a Task settlement record and
# model calls must link to attempts by stable id.
def test_r8_task_usage_is_aggregatable_for_settlement() -> None:
    task_properties = AgentTask.model_json_schema()["properties"]
    assert "usage" in task_properties
    assert "attempts" in task_properties
    response_properties = event_payload_schema_for(EventType.MODEL_RESPONSE_RECEIVED)["properties"]
    assert "attempt_id" in response_properties
