from datetime import UTC, datetime
from threading import Barrier, Lock

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.tools import ToolCall
from agent_runtime import run_local_harness

NOW = datetime(2026, 7, 14, 15, 0, tzinfo=UTC)


def test_simple_answer_does_not_create_subagent(tmp_path) -> None:
    gateway = ScriptedModelGateway(
        responses=(ScriptedModelResponse(completion=_completion("2")),)
    )

    result = run_local_harness(
        prompt="What is 1 + 1? Reply with the result.",
        title="Direct answer",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
    )

    assert result.attempt_result.metadata["assistant_message"] == "2"
    assert not _subagent_events(result.events)


def test_single_parent_tool_does_not_create_subagent(tmp_path) -> None:
    (tmp_path / "answer.txt").write_text("DIRECT-EVIDENCE\n", encoding="utf-8")
    gateway = ScriptedModelGateway(
        responses=tuple(
            ScriptedModelResponse(completion=completion)
            for completion in (
                _completion(
                    "Reading the single file.",
                    _call("files.read", {"path": "answer.txt"}, "parent_read"),
                ),
                _completion("DIRECT-EVIDENCE"),
                _completion("DIRECT-EVIDENCE"),
            )
        )
    )

    result = run_local_harness(
        prompt="Read answer.txt and return its content.",
        title="Direct parent tool",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
    )

    assert result.attempt_result.metadata["assistant_message"] == "DIRECT-EVIDENCE"
    assert not _subagent_events(result.events)


def test_parent_uses_sourced_readonly_child_result_for_final_answer(tmp_path) -> None:
    (tmp_path / "evidence.txt").write_text("RESEARCH-EVIDENCE\n", encoding="utf-8")
    research_call = _call(
        "agent.research",
        {
            "objective": "Read evidence.txt and report its evidence.",
            "delegation_reason": "Isolate evidence collection from synthesis.",
        },
        "research_call",
    )
    read_call = _call("files.read", {"path": "evidence.txt"}, "read_call")
    gateway = ScriptedModelGateway(
        responses=tuple(
            ScriptedModelResponse(completion=completion)
            for completion in (
                _completion("Delegating research.", research_call),
                _completion("Reading evidence.", read_call),
                _completion("The sourced evidence is RESEARCH-EVIDENCE."),
                _completion("PARENT-ANSWER: RESEARCH-EVIDENCE"),
                _completion("PARENT-ANSWER: RESEARCH-EVIDENCE"),
                _completion("PARENT-ANSWER: RESEARCH-EVIDENCE"),
            )
        )
    )

    result = run_local_harness(
        prompt="Delegate evidence collection, then answer from the child result.",
        title="Read-only research delegation",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
    )

    assert result.attempt_result.metadata["assistant_message"] == (
        "PARENT-ANSWER: RESEARCH-EVIDENCE"
    )
    assert result.run_result.model_calls_used == 3
    assert result.run_result.tool_calls_used == 1
    assert "agent.research" in {tool.name for tool in gateway.tool_requests[0]}
    assert tuple(tool.name for tool in gateway.tool_requests[1]) == (
        "files.read",
        "files.search",
        "git.status",
    )
    assert "agent.research" not in {tool.name for tool in gateway.tool_requests[1]}
    assert any(
        "Subagent delegation:" in message.content for message in gateway.requests[0]
    )
    assert any(
        "Subagent delegation:" in message.content for message in gateway.requests[4]
    )
    assert all(
        "Subagent delegation:" not in message.content
        for request in gateway.requests[1:4]
        for message in request
    )
    assert "evidence.txt" in gateway.requests[4][-1].content
    assert "RESEARCH-EVIDENCE" in gateway.requests[4][-1].content

    started = next(
        event for event in result.events if event.event_type is EventType.SUBAGENT_STARTED
    )
    completed = next(
        event for event in result.events if event.event_type is EventType.SUBAGENT_COMPLETED
    )
    assert started.payload["status"] == "running"
    assert completed.payload["status"] == "completed"
    assert completed.payload["source_count"] == 1
    assert completed.payload["confidence"] == 1.0
    assert "RESEARCH-EVIDENCE" not in str(started.payload)
    assert "RESEARCH-EVIDENCE" not in str(completed.payload)


def test_research_child_searches_then_reads_within_fixed_budget(tmp_path) -> None:
    (tmp_path / "located.txt").write_text("CHILD-SEARCH-PROOF\n", encoding="utf-8")
    gateway = ScriptedModelGateway(
        responses=tuple(
            ScriptedModelResponse(completion=completion)
            for completion in (
                _completion(
                    "Delegating.",
                    _call(
                        "agent.research",
                        {
                            "objective": "Find the proof.",
                            "delegation_reason": "Search and read require a bounded context.",
                        },
                        "research",
                    ),
                ),
                _completion(
                    "Searching.",
                    _call(
                        "files.search",
                        {"query": "CHILD-SEARCH-PROOF"},
                        "search",
                    ),
                ),
                _completion(
                    "Reading.",
                    _call("files.read", {"path": "located.txt"}, "read"),
                ),
                _completion("Child found CHILD-SEARCH-PROOF."),
                _completion("Parent confirmed CHILD-SEARCH-PROOF."),
                _completion("Parent confirmed CHILD-SEARCH-PROOF."),
            )
        )
    )

    result = run_local_harness(
        prompt="Delegate discovery of the proof.",
        title="Research child search and read",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
    )

    assert result.attempt_result.metadata["assistant_message"] == (
        "Parent confirmed CHILD-SEARCH-PROOF."
    )
    completed = next(
        event for event in result.events if event.event_type is EventType.SUBAGENT_COMPLETED
    )
    assert completed.payload["tool_calls_used"] == 2
    assert completed.payload["source_count"] == 2


def test_parent_corrects_missing_delegation_reason_before_child_creation(tmp_path) -> None:
    invalid_call = _call(
        "agent.research",
        {"objective": "Inspect the workspace evidence."},
        "invalid_research",
    )
    corrected_call = _call(
        "agent.research",
        {
            "objective": "Inspect the workspace evidence.",
            "delegation_reason": "The evidence collection is independently bounded.",
        },
        "corrected_research",
    )
    gateway = ScriptedModelGateway(
        responses=tuple(
            ScriptedModelResponse(completion=completion)
            for completion in (
                _completion("Delegating.", invalid_call),
                _completion("Correcting the delegation contract.", corrected_call),
                _completion("No workspace evidence was needed."),
                _completion("Parent completed after the corrected delegation."),
                _completion("Parent completed after the corrected delegation."),
            )
        )
    )

    result = run_local_harness(
        prompt="Perform a bounded independent workspace investigation.",
        title="Correct invalid delegation",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
    )

    started = [
        event for event in result.events if event.event_type is EventType.SUBAGENT_STARTED
    ]
    failed_tools = [
        event
        for event in result.events
        if event.event_type is EventType.TOOL_EXECUTION_FAILED
    ]
    assert result.attempt_result.metadata["assistant_message"] == (
        "Parent completed after the corrected delegation."
    )
    assert len(started) == 1
    assert len(failed_tools) == 1
    assert failed_tools[0].payload["tool_call_id"] == str(invalid_call.tool_call_id)
    assert any(
        message.role is MessageRole.TOOL
        and "delegation_reason" in message.content
        for message in gateway.requests[1]
    )


def test_parent_fans_out_bounded_research_and_preserves_provider_order(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("FANOUT-A\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("FANOUT-B\n", encoding="utf-8")
    gateway = ParallelResearchGateway()

    result = run_local_harness(
        prompt="Research both evidence files concurrently, then report the result.",
        title="Parallel read-only research delegation",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
    )

    assert result.attempt_result.metadata["assistant_message"] == "FANOUT-OK"
    assert result.attempt_result.metadata["parallel_batch_size"] == 2
    assert result.attempt_result.metadata["subagent_count"] == 2
    assert result.attempt_result.metadata["subagent_model_calls_used"] == 6
    assert result.attempt_result.metadata["subagent_tool_calls_used"] == 2
    assert result.attempt_result.metadata["subagent_source_count"] == 2
    assert result.attempt_result.metadata["subagent_completed_count"] == 2
    assert gateway.max_child_active == 2
    assert gateway.parent_result_ids == ["research_a", "research_b"]
    assert gateway.child_tool_manifests == [
        ("files.read", "files.search", "git.status"),
        ("files.read", "files.search", "git.status"),
    ]
    completed = [
        event
        for event in result.events
        if event.event_type is EventType.SUBAGENT_COMPLETED
    ]
    assert [event.payload["subagent_id"] for event in completed] == (
        result.attempt_result.metadata["subagent_ids"]
    )
    assert all("FANOUT-" not in str(event.payload) for event in completed)


class ParallelResearchGateway:
    def __init__(self) -> None:
        self._barrier = Barrier(2)
        self._lock = Lock()
        self._child_active = 0
        self.max_child_active = 0
        self.parent_result_ids: list[str] = []
        self.child_tool_manifests: list[tuple[str, ...]] = []

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        user_text = next(
            message.content for message in messages if message.role is MessageRole.USER
        )
        tool_messages = [message for message in messages if message.role is MessageRole.TOOL]
        if user_text.startswith("Gather evidence"):
            return self._complete_child(user_text, tool_messages, tools)
        if not tool_messages:
            return _completion(
                "Delegating both research tasks.",
                _call(
                    "agent.research",
                    {
                        "objective": "Read a.txt and report its evidence.",
                        "delegation_reason": "This is one independent evidence stream.",
                    },
                    "research_a",
                ),
                _call(
                    "agent.research",
                    {
                        "objective": "Read b.txt and report its evidence.",
                        "delegation_reason": "This is one independent evidence stream.",
                    },
                    "research_b",
                ),
            )
        self.parent_result_ids = [message.tool_call_id or "" for message in tool_messages]
        return _completion("FANOUT-OK")

    def _complete_child(
        self,
        user_text: str,
        tool_messages: list[SessionMessage],
        tools: tuple[ModelToolDefinition, ...],
    ) -> ModelCompletion:
        if tool_messages:
            marker = "FANOUT-A" if "FANOUT-A" in tool_messages[-1].content else "FANOUT-B"
            return _completion(f"Sourced evidence: {marker}")
        with self._lock:
            self._child_active += 1
            self.max_child_active = max(self.max_child_active, self._child_active)
            self.child_tool_manifests.append(tuple(tool.name for tool in tools))
        try:
            self._barrier.wait(timeout=2)
        finally:
            with self._lock:
                self._child_active -= 1
        path = "a.txt" if "a.txt" in user_text else "b.txt"
        return _completion(
            f"Reading {path}.",
            _call("files.read", {"path": path}, f"read_{path[0]}"),
        )


def _completion(content: str, *tool_calls: ToolCall) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=NOW,
        ),
        tool_calls=tool_calls,
    )


def _call(name: str, arguments: dict[str, object], provider_id: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=NOW,
        provider_call_id=provider_id,
    )


def _subagent_events(events: tuple[SessionEvent, ...]) -> list[SessionEvent]:
    lifecycle = {
        EventType.SUBAGENT_STARTED,
        EventType.SUBAGENT_COMPLETED,
        EventType.SUBAGENT_FAILED,
        EventType.SUBAGENT_CANCELLED,
    }
    return [event for event in events if event.event_type in lifecycle]
