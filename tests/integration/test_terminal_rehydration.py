import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import zebra_agent_api.app as api_app_module
import zebra_agent_worker.execution as worker_execution_module
from agent_context import LocalContextCompiler
from agent_context.capsule import build_context_capsule
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import apply_event, rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextCapsuleValidationContext,
    ContextSourceEventRange,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelContextWindow, ModelToolDefinition
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.session_handoff import HandoffReason
from agent_core.domain.sessions import Session
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessContext,
    HarnessLoop,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_core.harness.context_window import plan_context_window
from agent_core.harness.models import HarnessAttemptResult, HarnessEventDraft
from agent_core.ports.context_compiler import RuntimeEvidenceInput
from agent_storage import (
    SQLiteAgentTaskStore,
    SQLiteArtifactPayloadStore,
    SQLiteContextLifecycleStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteSessionHandoffStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_api.task_api import append_task_message
from zebra_agent_config import load_settings
from zebra_agent_worker.session_handoff import SessionHandoffRecoveryGate
from zebra_agent_worker.task_recovery import recover_task

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
COMPLETION_TOKEN = "COMPLETE-SYNTHETIC-TRANSACTION-LOG"
LATER_DECISION = "Use the corrected synthetic account label in the final log."
RECOVERED_ROW = "SYNTHETIC-ROW-2026-07-29-001"
SOURCE_GOAL_MARKER = "SYNTHETIC-ORIGINAL-OBJECTIVE-471"
SOURCE_DRAFT_MARKER = "SYNTHETIC-PRIOR-ASSISTANT-DRAFT-472"
SOURCE_VISIBLE_MARKER = "SYNTHETIC-PRIOR-VISIBLE-CONTEXT-473"
LONG_TAIL_MARKER = "SYNTHETIC-LONG-TAIL-14118-474"
FOLLOW_UP = "Confirmed: emit the final synthetic transaction log."
FOLLOW_UP_RESOLUTION_MARKER = "Apply the latest user follow-up before planning or requesting tools."
TERMINAL_CRITERION = (
    "Produce a final response that directly satisfies the original user objective "
    "using available evidence."
)
_LONG_REQUEST_PREFIX = (
    f"{SOURCE_GOAL_MARKER}: Produce the complete synthetic transaction log. "
    f"The final answer must include {COMPLETION_TOKEN}.\n"
)
_LONG_REQUEST_TAIL = f"\nRequired tail evidence: {LONG_TAIL_MARKER}.\n"
LONG_REQUEST = (
    _LONG_REQUEST_PREFIX
    + "x" * (12_100 - len(_LONG_REQUEST_PREFIX))
    + _LONG_REQUEST_TAIL
    + "x" * (14_118 - 12_100 - len(_LONG_REQUEST_TAIL))
)
TOOLS = (
    ModelToolDefinition(
        name="files.read",
        description="Read a synthetic fixture.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    ),
)


class AllowAllPolicy:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed",
            policy_profile="test",
        )


class SyntheticEvidenceTools:
    def __init__(self, *, padding_repetitions: int = 4_000) -> None:
        self._padding_repetitions = padding_repetitions

    def execute(self, tool_call: ToolCall) -> ToolResult:
        output = (
            "padding " * self._padding_repetitions
            + (RECOVERED_ROW if tool_call.arguments["query"] == "variant-0" else "repeat")
        )
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=output,
        )


class CompletionAwareGateway:
    def __init__(self, context_window: ModelContextWindow | None = None) -> None:
        self._cursor = 0
        self.context_window = context_window or ModelContextWindow()
        self.requests: list[tuple[SessionMessage, ...]] = []
        self.tool_requests: list[tuple[ModelToolDefinition, ...]] = []

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        self.requests.append(tuple(messages))
        self.tool_requests.append(tools)
        if not tools:
            if any(RECOVERED_ROW in message.content for message in messages):
                return _completion(f"{COMPLETION_TOKEN}: {RECOVERED_ROW}")
            return _completion("Need another read.", _call("terminal-repeat"))
        completion = _completion("Read more evidence.", _call(f"variant-{self._cursor}"))
        self._cursor += 1
        return completion


def test_capsule_preserves_completion_contract_and_later_user_decision() -> None:
    capsule = build_context_capsule(
        (
            _message(MessageRole.USER, LONG_REQUEST),
            _message(MessageRole.USER, LATER_DECISION),
        ),
        user_goal=LONG_REQUEST,
        created_at=NOW,
    )

    assert capsule.acceptance_criteria == (TERMINAL_CRITERION,)
    assert capsule.protected_user_constraints == (LATER_DECISION,)
    assert LATER_DECISION in capsule.decisions


def test_terminal_synthesis_recovers_compacted_long_evidence() -> None:
    gateway = CompletionAwareGateway()
    result = HarnessLoop().run(
        HarnessTask(title="Synthetic ledger", user_input=LONG_REQUEST),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            SyntheticEvidenceTools(),
            model_step=HarnessModelStep(
                available_tools=TOOLS,
                conversation_compactor=LocalContextCompiler(),
            ),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == (
        f"{COMPLETION_TOKEN}: {RECOVERED_ROW}"
    )
    assert gateway.tool_requests[-1] == ()
    assert gateway.tool_requests.count(()) == 1
    assert plan_context_window(gateway.requests[-1], (), gateway.context_window).within_budget


def test_terminal_recovery_cache_stays_within_the_provider_hard_limit() -> None:
    gateway = CompletionAwareGateway(
        ModelContextWindow(
            profile_name="small",
            context_tokens=6_000,
            max_output_tokens=200,
            compaction_reserve_tokens=100,
            protocol_reserve_tokens=100,
            compaction_trigger_reserve_tokens=100,
        )
    )
    model_step = HarnessModelStep(
        available_tools=TOOLS,
        conversation_compactor=LocalContextCompiler(),
    )
    result = HarnessLoop().run(
        HarnessTask(title="Small synthetic ledger", user_input="Produce a synthetic log."),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            SyntheticEvidenceTools(padding_repetitions=700),
            model_step=model_step,
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert gateway.tool_requests.count(()) == 1
    assert plan_context_window(
        model_step._recovery_messages, (), gateway.context_window
    ).within_budget
    assert plan_context_window(gateway.requests[-1], (), gateway.context_window).within_budget


def test_sync_execute_persists_the_same_validated_active_capsule_boundary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "sync-context.sqlite"

    def run_with_compaction(**kwargs):
        capsule = _source_capsule(
            objective=str(kwargs["prompt"]),
            source_range=None,
        )

        def completed_attempt(_context) -> HarnessAttemptResult:
            return HarnessAttemptResult(
                outcome=HarnessAttemptOutcome.COMPLETED,
                summary="synthetic draft completed",
                metadata={"assistant_message": SOURCE_DRAFT_MARKER},
                emitted_events=(
                    HarnessEventDraft(
                        event_type=EventType.CONTEXT_COMPACTED,
                        actor=EventActor.HARNESS,
                        payload={
                            "attempt_number": 1,
                            "before_tokens": 4_000,
                            "after_tokens": 160,
                            "removed_message_count": 6,
                            "retained_message_count": 2,
                            "within_budget": True,
                            "provenance": "synthetic-test",
                            "capsule": capsule.model_dump(mode="json"),
                        },
                    ),
                ),
            )

        return HarnessLoop().run(
            HarnessTask(
                title=str(kwargs["title"]),
                user_input=str(kwargs["prompt"]),
                workspace_root=Path(kwargs["workspace_root"]),
            ),
            completed_attempt,
            created_at=NOW,
        )

    monkeypatch.setattr(api_app_module, "build_model_gateway", lambda _settings: object())
    monkeypatch.setattr(api_app_module, "run_local_harness", run_with_compaction)
    response = RouteAdapter(create_app(database)).handle(
        RouteRequest(
            method="POST",
            path="/tasks",
            body={
                "title": "Synthetic sync task",
                "prompt": LONG_REQUEST,
                "workspace": str(tmp_path),
                "execute": True,
            },
        )
    )

    assert response.status_code == 201
    active = SQLiteContextLifecycleStore(database).get_active_capsule(
        SessionId(UUID(response.body["session_id"]))
    )
    assert active is not None
    assert active.capsule.objective == LONG_REQUEST
    assert active.capsule.acceptance_criteria == (TERMINAL_CRITERION,)
    assert active.capsule.decisions_and_rationale == (SOURCE_DRAFT_MARKER,)


def test_terminal_follow_up_prioritizes_the_current_user_resolution_before_tools(
    tmp_path: Path,
) -> None:
    database = tmp_path / "follow-up.sqlite"
    task_id, source_id = _seed_completed_task_with_active_capsule(database, tmp_path)
    assert not any(
        event.event_type is EventType.CLARIFICATION_REQUESTED
        for event in SQLiteEventStore(database).list_for_session(source_id)
    )
    app = create_app(database, settings=load_settings({"ZEBRA_SESSION_HANDOFF_ENABLED": "true"}))

    appended = append_task_message(
        app,
        str(task_id),
        {"content": FOLLOW_UP},
        idempotency_key="synthetic-terminal-follow-up",
    )

    assert appended.status_code == 201
    child_id = SQLiteAgentTaskStore(database).active_segment(task_id)
    assert child_id is not None
    lineage = SQLiteSessionHandoffStore(database).get_lineage(child_id)
    handoff_id = lineage[-1].inbound_handoff_id
    assert handoff_id is not None
    envelope = SQLiteSessionHandoffStore(database).get_envelope(handoff_id)
    assert envelope is not None
    assert envelope.objective == LONG_REQUEST
    assert envelope.acceptance_criteria == (TERMINAL_CRITERION,)
    assert envelope.decisions_and_rationale == (SOURCE_DRAFT_MARKER,)
    assert envelope.completed_work == ()
    assert envelope.source_context_capsule_id is not None

    recovered = SessionHandoffRecoveryGate(str(database)).recover(
        child_id,
        worker_id="synthetic-worker",
        recovered_at=NOW,
    )
    assert recovered is not None
    assert recovered.source_capsule is not None
    assert recovered.source_capsule.objective == LONG_REQUEST
    assert recovered.source_capsule.source_event_range == ContextSourceEventRange(
        start_sequence=0,
        end_sequence=5,
    )
    assert recovered.runtime_evidence.metadata["handoff_source"] == "active_projection"
    assert recovered.runtime_evidence.metadata["handoff_reason"] == (
        HandoffReason.INTERNAL_TERMINAL_FOLLOW_UP.value
    )
    assert recovered.runtime_evidence.metadata["source_event_hash"] == envelope.source_event_hash
    assert recovered.runtime_evidence.metadata["source_event_range"] == {
        "start_sequence": 0,
        "end_sequence": 6,
    }
    assert LONG_REQUEST.index(LONG_TAIL_MARKER) > 12_000
    assert "completed_work" not in recovered.runtime_evidence.metadata
    assert "visible_conversation" not in recovered.runtime_evidence.metadata

    workspace = SQLiteWorkspaceProjectionStore(database).get_workspace(child_id)
    assert workspace is not None
    task = recover_task(
        SQLiteEventStore(database).list_for_session(child_id),
        workspace=workspace,
        fallback_title="Synthetic child",
        attachment_store=SQLiteArtifactPayloadStore(database),
        handoff_evidence=recovered.runtime_evidence,
    )
    gateway = RehydratedCompletionGateway()
    result = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicy(),
        SyntheticEvidenceTools(),
        model_step=HarnessModelStep(
            available_tools=TOOLS,
            context_compiler=LocalContextCompiler(),
        ),
    ).run(
        HarnessContext(
            task=HarnessTask(
                title=task.title,
                user_input=task.user_input,
                workspace_root=task.workspace_root,
                runtime_evidence=task.runtime_evidence,
            ),
            session=Session.create(title=task.title, created_at=NOW),
            attempt=HarnessAttempt(number=1, started_at=NOW),
        )
    )

    assert result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.metadata["assistant_message"] == (
        f"{COMPLETION_TOKEN}: {RECOVERED_ROW}"
    )
    assert len(gateway.requests) == 1
    assert gateway.tool_requests == [TOOLS]
    assert gateway.repeated_clarification is False


def test_active_projection_keeps_tools_for_a_genuinely_new_follow_up(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class NewFollowUpGateway:
        def __init__(self) -> None:
            self.tool_requests: list[tuple[ModelToolDefinition, ...]] = []

        def complete(
            self,
            messages: list[SessionMessage],
            *,
            tools: tuple[ModelToolDefinition, ...] = (),
        ) -> ModelCompletion:
            self.tool_requests.append(tools)
            assert messages[-1].content == "Inspect a distinct new follow-up."
            assert FOLLOW_UP_RESOLUTION_MARKER not in "\n".join(
                message.content for message in messages
            )
            return _completion("The distinct follow-up is complete.")

    gateway = NewFollowUpGateway()
    result = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicy(),
        SyntheticEvidenceTools(),
        model_step=HarnessModelStep(
            available_tools=TOOLS,
            context_compiler=LocalContextCompiler(),
        ),
    ).run(
        HarnessContext(
            task=HarnessTask(
                title="New follow-up",
                user_input="Inspect a distinct new follow-up.",
                workspace_root=workspace.resolve(),
                runtime_evidence=(
                    RuntimeEvidenceInput(
                        kind="session_handoff",
                        summary="Continue the verified task.",
                        metadata={
                            "handoff_source": "active_projection",
                            "handoff_reason": HandoffReason.USER_PHASE_BOUNDARY.value,
                        },
                    ),
                ),
            ),
            session=Session.create(title="New follow-up", created_at=NOW),
            attempt=HarnessAttempt(number=1, started_at=NOW),
        )
    )

    assert result.outcome is HarnessAttemptOutcome.COMPLETED
    assert gateway.tool_requests == [TOOLS]


def test_terminal_follow_up_falls_back_to_checkpoint_when_active_capsule_is_corrupt(
    tmp_path: Path,
) -> None:
    database = tmp_path / "corrupt-follow-up.sqlite"
    task_id, _source_id = _seed_completed_task_with_active_capsule(database, tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE context_capsule_artifacts SET payload = ?", (b"{}",))

    appended = append_task_message(
        create_app(database, settings=load_settings({"ZEBRA_SESSION_HANDOFF_ENABLED": "true"})),
        str(task_id),
        {"content": FOLLOW_UP},
        idempotency_key="corrupt-terminal-follow-up",
    )

    assert appended.status_code == 201
    child_id = SQLiteAgentTaskStore(database).active_segment(task_id)
    assert child_id is not None
    lineage = SQLiteSessionHandoffStore(database).get_lineage(child_id)
    handoff_id = lineage[-1].inbound_handoff_id
    assert handoff_id is not None
    envelope = SQLiteSessionHandoffStore(database).get_envelope(handoff_id)
    assert envelope is not None
    assert envelope.source_context_capsule_id is None
    assert envelope.completed_work[0].startswith("Prior user request: ")
    assert any("bounded checkpoint fallback" in item for item in envelope.known_omissions)


def test_terminal_follow_up_rejects_a_tampered_source_event_slice(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tampered-source.sqlite"
    task_id, source_id = _seed_completed_task_with_active_capsule(database, tmp_path)
    app = create_app(database, settings=load_settings({"ZEBRA_SESSION_HANDOFF_ENABLED": "true"}))
    appended = append_task_message(
        app,
        str(task_id),
        {"content": FOLLOW_UP},
        idempotency_key="tampered-source-follow-up",
    )
    assert appended.status_code == 201
    child_id = SQLiteAgentTaskStore(database).active_segment(task_id)
    assert child_id is not None
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE session_events SET payload = ? WHERE session_id = ? AND sequence = 0",
            (json.dumps({"tampered": True}), str(source_id)),
        )

    with pytest.raises(ValueError, match="source event hash does not match"):
        SessionHandoffRecoveryGate(str(database)).recover(
            child_id,
            worker_id="synthetic-worker",
            recovered_at=NOW,
        )


def test_child_worker_emits_final_marker_without_reasking_for_projected_details(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "worker-follow-up.sqlite"
    task_id, _source_id = _seed_completed_task_with_active_capsule(database, tmp_path)
    app = create_app(database, settings=load_settings({"ZEBRA_SESSION_HANDOFF_ENABLED": "true"}))
    appended = append_task_message(
        app,
        str(task_id),
        {"content": FOLLOW_UP},
        idempotency_key="worker-terminal-follow-up",
    )
    assert appended.status_code == 201
    child_id = SQLiteAgentTaskStore(database).active_segment(task_id)
    assert child_id is not None
    gateway = WorkerRehydratedCompletionGateway()
    monkeypatch.setattr(worker_execution_module, "build_model_gateway", lambda _settings: gateway)

    resumed = app.resume_session(
        str(child_id),
        {"worker_id": "synthetic-worker", "lease_ttl_seconds": 30},
    )

    assert resumed.status_code == 200
    assert resumed.body["status"] == "completed"
    assert resumed.body["assistant_message"] == f"{COMPLETION_TOKEN}: {RECOVERED_ROW}"
    assert len(gateway.task_requests) == 1


class RehydratedCompletionGateway:
    def __init__(self) -> None:
        self.requests: list[tuple[SessionMessage, ...]] = []
        self.tool_requests: list[tuple[ModelToolDefinition, ...]] = []
        self.repeated_clarification = False

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        self.requests.append(tuple(messages))
        self.tool_requests.append(tools)
        rendered = "\n".join(message.content for message in messages)
        assert messages[-1].role is MessageRole.USER
        assert messages[-1].content == FOLLOW_UP
        assert SOURCE_GOAL_MARKER in rendered
        assert SOURCE_DRAFT_MARKER in rendered
        assert LONG_TAIL_MARKER in rendered
        assert SOURCE_VISIBLE_MARKER not in rendered
        assert TERMINAL_CRITERION in rendered
        if FOLLOW_UP_RESOLUTION_MARKER not in rendered:
            self.repeated_clarification = True
            return _completion("Need the same confirmation again.", _clarify_call())
        return _completion(f"{COMPLETION_TOKEN}: {RECOVERED_ROW}")


class WorkerRehydratedCompletionGateway:
    def __init__(self) -> None:
        self.task_requests: list[tuple[SessionMessage, ...]] = []

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        rendered = "\n".join(message.content for message in messages)
        if SOURCE_GOAL_MARKER not in rendered:
            return _completion("Synthetic transaction task")
        self.task_requests.append(tuple(messages))
        assert SOURCE_DRAFT_MARKER in rendered
        assert LONG_TAIL_MARKER in rendered
        assert SOURCE_VISIBLE_MARKER not in rendered
        assert TERMINAL_CRITERION in rendered
        return _completion(f"{COMPLETION_TOKEN}: {RECOVERED_ROW}")


def _seed_completed_task_with_active_capsule(
    database: Path,
    workspace: Path,
):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Synthetic terminal task",
            user_input=LONG_REQUEST,
            workspace_root=workspace.resolve(),
            created_at=NOW,
        )
    )
    events = [
        *bootstrap.events,
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=3,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=4,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={"assistant_message": SOURCE_DRAFT_MARKER},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=5,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "synthetic draft complete"},
            created_at=NOW,
        ),
    ]
    event_store = SQLiteEventStore(database)
    for event in events:
        event_store.append(event)
    session = rebuild_session(events)
    SQLiteProjectionStore(database).save_session(session)
    SQLiteWorkspaceProjectionStore(database).save_workspace(rebuild_workspace(events))

    capsule = _source_capsule(
        objective=LONG_REQUEST,
        source_range=ContextSourceEventRange(start_sequence=0, end_sequence=5),
    )
    lifecycle = SQLiteContextLifecycleStore(database)
    stored = lifecycle.persist_capsule_and_advance(
        session_id=session.session_id,
        capsule=capsule,
        validation_context=ContextCapsuleValidationContext(
            expected_source_hash=capsule.source_hash,
            expected_source_event_range=capsule.source_event_range,
            protected_user_constraints=frozenset(capsule.protected_user_constraints),
            approval_and_policy_state=frozenset(capsule.approvals_and_policy_state),
            readable_artifact_refs=frozenset(capsule.referenced_artifact_refs),
        ),
        sequence=6,
        expected_active_capsule_id=None,
        created_at=NOW,
    )
    SQLiteProjectionStore(database).save_session(apply_event(session, stored.event))
    task = SQLiteAgentTaskStore(database).ensure_for_session(session.session_id)
    return task.task_id, session.session_id


def _source_capsule(
    *,
    objective: str,
    source_range: ContextSourceEventRange | None,
) -> ContextCapsule:
    return ContextCapsule(
        capsule_id="synthetic-capsule-471",
        objective=objective,
        acceptance_criteria=(TERMINAL_CRITERION,),
        constraints=(objective,),
        protected_user_constraints=(LATER_DECISION,),
        decisions=(SOURCE_DRAFT_MARKER,),
        decisions_and_rationale=(SOURCE_DRAFT_MARKER,),
        plan=(f"Draft exchange: {SOURCE_VISIBLE_MARKER}",),
        tests=(RECOVERED_ROW,),
        immediate_next="Await the synthetic confirmation.",
        source_event_range=source_range,
        source_hash="a" * 64,
        confidence=1.0,
        created_at=NOW,
    )


def _completion(content: str, *tool_calls: ToolCall) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=_message(MessageRole.ASSISTANT, content),
        tool_calls=tool_calls,
    )


def _call(query: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"query": query},
        created_at=NOW,
        provider_call_id=query,
    )


def _clarify_call() -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.clarify",
        arguments={"question": "Should the recorded item be included?"},
        created_at=NOW,
        provider_call_id="repeat-clarification",
    )


def _message(role: MessageRole, content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=role,
        content=content,
        created_at=NOW,
    )
