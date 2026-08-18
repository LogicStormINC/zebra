"""Wave 5 Gate 1 correction red tests (root independent audit)."""

import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.application.public_conversation import project_public_conversation
from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import (
    EventId,
    new_message_id,
    new_tool_call_id,
)
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.tools import ToolCall, ToolCallId
from agent_storage import (
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from wave5_gate1_corrections_support import (
    _attempt_started,
    _ExplodingGateway,
    _outcomes,
    _RecordingGateway,
    _seed,
)
from worker_execution_support import _build_execution_service, _created_at
from zebra_agent_api.task_final_identity import final_message_identity
from zebra_agent_worker import SessionRecoveryService


# C1 (blocker 1): W5-DSH-01 real-dispatch guard - each independent
# reconstructed axis (messages/system/tools/model config) must fail closed
# before the model gateway is called when mutated.
def test_c1_dispatch_fails_closed_on_reconstruction_mismatch() -> None:
    from agent_core.domain.modeling import ModelToolDefinition
    from agent_core.harness.model_step import HarnessModelStep
    from agent_core.harness.reconstruction import (
        ReconstructionMismatchError,
        RequestReconstruction,
        media_inputs_digest,
        model_config_digest,
        system_prompt_digest,
        tool_schema_digest,
    )

    messages = [
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.SYSTEM,
            content="durable system prompt",
            created_at=_created_at(),
        ),
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.USER,
            content="original durable user input",
            created_at=_created_at(),
        ),
    ]
    tools = (
        ModelToolDefinition(
            name="files.read",
            description="read a file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        ),
    )

    class _IdentityGateway:
        provider = "test"
        model_name = "test-model"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages, *, tools=()):
            self.calls += 1
            return None

        def complete_stream(self, messages, *, tools=(), on_text_delta=None):
            self.calls += 1
            return None

    def base_reconstruction(**overrides):
        kwargs = dict(
            stable_task_id="task-1",
            attempt_id="attempt-1",
            turn_id="turn-1",
            goal_revision=1,
            plan_revision=1,
            messages_rebuild=lambda: messages,
            system_prompt_digest=system_prompt_digest(messages),
            tool_schema_digest=tool_schema_digest(tools),
            media_digest=media_inputs_digest(()),
            model_config_digest=model_config_digest("test:test-model"),
        )
        kwargs.update(overrides)
        return RequestReconstruction(**kwargs)

    axes = {
        "messages": lambda: base_reconstruction(
            messages_rebuild=lambda: [
                SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.USER,
                    content="mutated durable user input",
                    created_at=_created_at(),
                )
            ]
        ),
        "system": lambda: base_reconstruction(
            system_prompt_digest=system_prompt_digest(
                [
                    SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.SYSTEM,
                        content="different durable system prompt",
                        created_at=_created_at(),
                    )
                ]
            )
        ),
        "tools": lambda: base_reconstruction(
            tool_schema_digest=tool_schema_digest(
                (
                    ModelToolDefinition(
                        name="files.write",
                        description="write a file",
                        parameters={
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                    ),
                )
            )
        ),
        "model_config": lambda: base_reconstruction(
            model_config_digest=model_config_digest("test:other-model")
        ),
    }
    for axis, build in axes.items():
        gateway = _IdentityGateway()
        model_step = HarnessModelStep(reconstruction=build())
        model_step._available_tools = tools
        with pytest.raises(ReconstructionMismatchError, match="differs from the durable"):
            model_step.request_completion(
                messages,
                gateway,
                allow_tools=True,
            )
        assert gateway.calls == 0, f"axis {axis} did not fail closed"


# C2 (blocker 1 wiring): dispatch events must populate the private
# reconstruction coordinates and digests.
def test_c2_dispatch_events_populate_reconstruction_coordinates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "corrections-c2.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    from worker_execution_support import _assistant_only_gateway

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="corrections-red-c2",
        executed_at=_created_at(),
    )
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    requested = [event for event in events if event.event_type is EventType.MODEL_REQUEST_STARTED]
    assert requested
    for key in (
        "stable_task_id",
        "attempt_id",
        "turn_id",
        "step_id",
        "goal_revision",
        "plan_revision",
        "messages_digest",
        "system_prompt_digest",
        "tool_schema_digest",
        "model_config_digest",
        "resource_manifest_digest",
    ):
        assert key in requested[0].payload
    for key in (
        "messages_digest",
        "system_prompt_digest",
        "tool_schema_digest",
        "model_config_digest",
        "resource_manifest_digest",
        "invocation_policy_digest",
    ):
        value = requested[0].payload[key]
        assert isinstance(value, str)
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", value)


# C3 (blocker 2): a corrupted durable policy must fail closed before the
# gateway (present invalid values never fall back to defaults).
def test_c3_corrupted_durable_policy_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "corrections-c3.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    event_store = SQLiteEventStore(database_path)
    corrupted = SessionEvent(
        event_id=EventId(uuid4()),
        session_id=session_id,
        sequence=3,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={
            "title": "drifted",
            "user_input": "continue",
            "max_attempts": 0,
        },
        created_at=_created_at(),
    )
    event_store.append(corrupted)
    SQLiteProjectionStore(database_path).save_session(apply_event(bootstrap.session, corrupted))
    gateway = _RecordingGateway()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )

    with pytest.raises(Exception) as excinfo:
        _build_execution_service(database_path).execute_session(
            session_id,
            worker_id="corrections-red-c3",
            executed_at=_created_at(),
        )

    assert "policy" in str(excinfo.value).lower() or "attempt" in str(excinfo.value).lower()
    assert gateway.calls == []


# C4 (blocker 2): an explicitly frozen empty retry set must stay empty - a
# retryable failure must not start Attempt 2.
def test_c4_explicit_empty_retry_set_is_preserved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "corrections-c4.db"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="No retries",
            user_input="fail once",
            workspace_root=tmp_path.resolve(),
            tool_profile=ToolProfile.CODING,
            max_attempts=2,
            retryable_stop_reasons=(),
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
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _ExplodingGateway(),
    )
    _build_execution_service(database_path).execute_session(
        bootstrap.session.session_id,
        worker_id="corrections-red-c4",
        executed_at=_created_at(),
    )
    events = event_store.list_for_session(bootstrap.session.session_id)
    assert [event.payload["attempt_sequence"] for event in _attempt_started(events)] == [1]
    failed = [event for event in events if event.event_type is EventType.SESSION_FAILED]
    assert len(failed) == 1
    assert failed[0].payload["attempt_number"] == 1


# C5 (blocker 3 refinement): a Wave 5 candidate final stays private until an
# authoritative accepted attempt fact exists; failed/retrying/no-outcome
# candidates never bind the final identity.
def test_c5_failed_attempt_candidate_final_stays_private_before_terminal(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "corrections-c5.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    epoch_turn = f"turn:{bootstrap.events[1].event_id}"
    event_store = SQLiteEventStore(database_path)
    candidate = SessionEvent.create(
        session_id=session_id,
        sequence=3,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "attempt_id": "attempt-1",
            "model_call_id": "call-1",
            "assistant_message": "attempt-1 candidate final",
            "response_stage": "final",
        },
        created_at=_created_at(),
    )
    retry_outcome = SessionEvent.create(
        session_id=session_id,
        sequence=4,
        event_type=EventType.ATTEMPT_OUTCOME_RECORDED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_id": "attempt-1",
            "attempt_sequence": 1,
            "outcome": "failed",
            "ended_at": _created_at().isoformat(),
            "terminal_reason": "model_execution_failed",
            "retry_scheduled": True,
            "next_attempt_sequence": 2,
            "turn_id": epoch_turn,
            "epoch_sequence": 0,
        },
        created_at=_created_at(),
    )
    session = bootstrap.session
    for event in (candidate, retry_outcome):
        event_store.append(event)
        session = apply_event(session, event)
    SQLiteProjectionStore(database_path).save_session(session)
    task = SQLiteAgentTaskStore(database_path).ensure_for_session(session_id)
    task_events = SQLiteAgentTaskStore(database_path).read_events(task.task_id, -1)
    projection = project_public_conversation(task.task_id, task_events)
    assert not any(item.role == "final_response" for item in projection.items)
    assert final_message_identity(database_path, str(task.task_id)) is None


def test_c5_accepted_attempt_final_becomes_visible_once(tmp_path: Path) -> None:
    database_path = tmp_path / "corrections-c5b.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=1)
    session_id = bootstrap.session.session_id
    epoch_turn = f"turn:{bootstrap.events[1].event_id}"
    event_store = SQLiteEventStore(database_path)
    additions = (
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "attempt_id": "attempt-1",
                "attempt_sequence": 1,
                "started_at": _created_at().isoformat(),
                "turn_id": epoch_turn,
                "epoch_sequence": 0,
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=4,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "attempt_id": "attempt-1",
                "model_call_id": "call-1",
                "assistant_message": "accepted final",
                "response_stage": "final",
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=5,
            event_type=EventType.ATTEMPT_OUTCOME_RECORDED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_id": "attempt-1",
                "attempt_sequence": 1,
                "outcome": "completed",
                "ended_at": _created_at().isoformat(),
                "terminal_reason": "completed",
                "retry_scheduled": False,
                "next_attempt_sequence": None,
                "summary": "accepted",
                "turn_id": epoch_turn,
                "epoch_sequence": 0,
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=6,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1, "summary": "accepted"},
            created_at=_created_at(),
        ),
    )
    session = bootstrap.session
    for event in additions:
        event_store.append(event)
        session = apply_event(session, event)
    SQLiteProjectionStore(database_path).save_session(session)
    task = SQLiteAgentTaskStore(database_path).ensure_for_session(session_id)
    task_events = SQLiteAgentTaskStore(database_path).read_events(task.task_id, -1)
    projection = project_public_conversation(task.task_id, task_events)
    finals = [item for item in projection.items if item.role == "final_response"]
    assert len(finals) == 1
    assert finals[0].content == "accepted final"
    assert final_message_identity(database_path, str(task.task_id)) is not None


# C6 (blocker 4): an Attempt-2 clarification continuation must resume the
# SAME attempt with its identity, never fail closed or create Attempt 3.
def test_c6_attempt_2_clarification_continuation_resumes_same_attempt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "corrections-c6.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id
    epoch_turn = f"turn:{bootstrap.events[1].event_id}"
    event_store = SQLiteEventStore(database_path)
    clarify_id = str(uuid4())
    clarify_call = ToolCall(
        tool_call_id=ToolCallId(UUID(clarify_id)),
        name="agent.clarify",
        arguments={"question": "which account?"},
        created_at=_created_at(),
    )
    conversation = [
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.USER,
            content="Continue the queued task.",
            created_at=_created_at(),
        ).model_dump(mode="json"),
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="need input",
            created_at=_created_at(),
            tool_calls=(clarify_call,),
        ).model_dump(mode="json"),
    ]
    additions = (
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "attempt_id": "attempt-1",
                "attempt_sequence": 1,
                "started_at": _created_at().isoformat(),
                "turn_id": epoch_turn,
                "epoch_sequence": 0,
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=4,
            event_type=EventType.ATTEMPT_OUTCOME_RECORDED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_id": "attempt-1",
                "attempt_sequence": 1,
                "outcome": "failed",
                "ended_at": _created_at().isoformat(),
                "terminal_reason": "model_execution_failed",
                "retry_scheduled": True,
                "next_attempt_sequence": 2,
                "turn_id": epoch_turn,
                "epoch_sequence": 0,
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=5,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 2,
                "attempt_id": "attempt-2",
                "attempt_sequence": 2,
                "started_at": _created_at().isoformat(),
                "causal_attempt_id": "attempt-1",
                "turn_id": epoch_turn,
                "epoch_sequence": 0,
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=6,
            event_type=EventType.CLARIFICATION_REQUESTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 2,
                "clarification_id": clarify_id,
                "tool_call_id": clarify_id,
                "question": "which account?",
                "choices": [],
                "conversation": conversation,
                "assistant_message": "need input",
                "model_calls_used": 1,
                "tool_calls_executed": 0,
            },
            created_at=_created_at(),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=7,
            event_type=EventType.CLARIFICATION_RESPONDED,
            actor=EventActor.USER,
            payload={
                "clarification_id": clarify_id,
                "content": "use account A",
                "selected_choice": False,
            },
            created_at=_created_at(),
        ),
    )
    session = bootstrap.session
    for event in additions:
        event_store.append(event)
        session = apply_event(session, event)
    SQLiteProjectionStore(database_path).save_session(session)
    from worker_execution_support import _assistant_only_gateway

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="corrections-red-c6",
        executed_at=_created_at(),
    )
    events = event_store.list_for_session(session_id)
    started = _attempt_started(events)
    assert [event.payload["attempt_sequence"] for event in started] == [1, 2]
    assert not any(
        event.payload.get("terminal_reason") == "attempt_reconstruction_invalid"
        for event in _outcomes(events)
    )
    markers = [
        event for event in events if event.event_type is EventType.ATTEMPT_CONTINUATION_STARTED
    ]
    assert markers
    assert markers[0].payload["attempt_id"] == "attempt-2"


# C7 (blocker 5): a durable Plan updated during Attempt 1 must flow into
# Attempt 2's request reconstruction with an incremented revision.
def test_c7_attempt_2_uses_durable_plan_revision_from_attempt_1(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "corrections-c7.db"
    bootstrap = _seed(database_path, tmp_path, max_attempts=2)
    session_id = bootstrap.session.session_id

    def exploding_after_plan():
        return ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="Proposing a plan.",
                            created_at=_created_at(),
                        ),
                        tool_calls=(
                            ToolCall(
                                tool_call_id=new_tool_call_id(),
                                name="agent.plan",
                                arguments={
                                    "steps": [
                                        {
                                            "step_id": "s1",
                                            "content": "step one",
                                            "status": "pending",
                                        }
                                    ]
                                },
                                created_at=_created_at(),
                            ),
                        ),
                    )
                ),
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="unused",
                            created_at=_created_at(),
                        )
                    )
                ),
            )
        )

    class _ExplodeAfterPlan:
        provider = "test"
        model_name = "test-model"

        def __init__(self) -> None:
            self._inner = exploding_after_plan()
            self._calls = 0

        def complete(self, messages, *, tools=()):
            return self._dispatch(messages, tools=tools)

        def complete_stream(self, messages, *, tools=(), on_text_delta=None):
            return self._dispatch(messages, tools=tools)

        def _dispatch(self, messages, *, tools):
            self._calls += 1
            if self._calls == 1:
                # Dispatch 1 returns the agent.plan tool call so the harness
                # executes it and durably records PLAN_UPDATED inside
                # Attempt 1.
                return self._inner.complete(messages, tools=tools)
            if self._calls == 2:
                # Dispatch 2 (after the plan tool result) fails retriably,
                # ending Attempt 1.
                raise RuntimeError("provider transport exploded")
            return self._inner.complete(messages, tools=tools)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _ExplodeAfterPlan(),
    )
    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="corrections-red-c7",
        executed_at=_created_at(),
    )
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    requested = [event for event in events if event.event_type is EventType.MODEL_REQUEST_STARTED]
    assert len(requested) >= 2
    attempt_2_request = next(
        event for event in requested if event.payload.get("attempt_number") == 2
    )
    assert attempt_2_request.payload["plan_revision"] == 2
    # The actual request envelope must contain the durable Plan updated
    # during Attempt 1: the Attempt-2 system prompt digest differs from
    # Attempt-1's because task_state_context renders the current plan.
    assert (
        attempt_2_request.payload["system_prompt_digest"]
        != requested[0].payload["system_prompt_digest"]
    )
