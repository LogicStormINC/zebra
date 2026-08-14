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
    _tool_gateway,
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


# R4 (W5-DSH-02): durable attempt coordinates checked at the existing
# lifecycle seams - start coordinates on HARNESS_ATTEMPT_STARTED, terminal
# coordinates on the terminal events. The owner contract requires lifecycle
# identity/sequence/started/ended time/terminal reason/causal reference, not
# every field on the start event.
def test_r4_attempt_start_coordinates_at_start_seam() -> None:
    schema = event_payload_schema_for(EventType.HARNESS_ATTEMPT_STARTED)
    properties = schema["properties"]
    for field in (
        "attempt_id",
        "attempt_sequence",
        "started_at",
        "causal_attempt_id",
    ):
        assert field in properties


def test_r4_attempt_terminal_coordinates_at_terminal_seam() -> None:
    for terminal_type in (EventType.SESSION_COMPLETED, EventType.SESSION_FAILED):
        schema = event_payload_schema_for(terminal_type)
        properties = schema["properties"]
        for field in ("attempt_id", "ended_at", "terminal_reason"):
            assert field in properties


# R5 (W5-DSH-01): behavioral fail-closed at the real dispatch seam - when the
# durable stream's attempt coordinate differs from the worker reconstruction,
# execution must fail closed BEFORE the model gateway is called.
def test_r5_dispatch_fails_closed_on_reconstruction_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "wave5-r5.db"
    bootstrap = _seed_session(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    durable_attempt = SessionEvent.create(
        session_id=session_id,
        sequence=3,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 2},
        created_at=_created_at(),
    )
    event_store = SQLiteEventStore(database_path)
    event_store.append(durable_attempt)
    projected_session = apply_event(bootstrap.session, durable_attempt)
    SQLiteProjectionStore(database_path).save_session(projected_session)

    calls: list[str] = []

    class _RecordingGateway:
        def complete(self, messages, *, tools=()):
            calls.append("complete")
            raise AssertionError("dispatch must fail closed before gateway call")

        def complete_stream(self, messages, *, tools=(), on_text_delta=None):
            calls.append("complete_stream")
            raise AssertionError("dispatch must fail closed before gateway call")

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _RecordingGateway(),
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="wave5-red-r5",
        executed_at=_created_at(),
    )

    events = event_store.list_for_session(session_id)
    started = [event for event in events if event.event_type is EventType.HARNESS_ATTEMPT_STARTED]
    assert calls == []
    assert started[-1].payload["attempt_id"] == "attempt-2"


# R5 supporting schema assertion: the durable request payload must accept the
# private reconstruction coordinates.
def test_r5_model_request_payload_schema_supports_reconstruction_coordinates() -> None:
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


# R8: behavioral - one Stable Task's usage equals the sum of its attempt
# usages, and every usage-bearing event links to a stable attempt identity,
# computed at the existing task-event seam (no storage shape prescribed).
def test_r8_task_usage_equals_sum_of_attempt_usages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "wave5-r8.db"
    bootstrap = _seed_session(database_path, tmp_path, max_attempts=1)
    session_id = bootstrap.session.session_id
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _tool_gateway(settings=settings),
    )
    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="wave5-red-r8",
        executed_at=_created_at(),
    )
    task_store = SQLiteAgentTaskStore(database_path)
    task = task_store.ensure_for_session(session_id)
    task_events = task_store.read_events(task.task_id, -1)
    usage_events = [
        item.event
        for item in task_events
        if item.event.event_type is EventType.MODEL_RESPONSE_RECEIVED
        and item.event.payload.get("total_tokens") is not None
    ]
    attempt_started = [
        item.event
        for item in task_events
        if item.event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    assert usage_events
    per_attempt: dict[str, int] = {}
    for usage in usage_events:
        attempt_id = usage.payload["attempt_id"]  # base: KeyError -> red
        assert attempt_id in {event.payload["attempt_id"] for event in attempt_started}
        per_attempt[attempt_id] = per_attempt.get(attempt_id, 0) + int(
            usage.payload["total_tokens"]
        )
    assert sum(per_attempt.values()) == sum(
        int(usage.payload["total_tokens"]) for usage in usage_events
    )
