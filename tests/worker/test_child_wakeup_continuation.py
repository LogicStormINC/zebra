from datetime import UTC, datetime
from uuid import uuid4

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id, new_session_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.parent_continuation import ChildTerminalStatus
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tools import ToolCall
from agent_core.harness.protocol_invariants import validate_tool_call_pairing
from agent_storage.postgres.subagent_delegation import canonical_child_terminal_summary
from zebra_agent_worker.child_wakeup import child_terminal_status
from zebra_agent_worker.child_wakeup_continuation import (
    ChildResultDelivery,
    ChildWakeupContinuation,
    recover_child_wakeup_continuation,
)
from zebra_agent_worker.continuation_dispatch import (
    child_wakeup_evidence_conversation,
    child_wakeup_tool_results,
)


def test_child_wakeup_recovery_preserves_parent_budget_counters() -> None:
    parent = new_session_id()
    child = str(uuid4())
    tool_call = str(uuid4())
    now = datetime.now(UTC)
    events = [
        SessionEvent.create(
            session_id=parent,
            sequence=0,
            event_type=EventType.SUBAGENT_DELEGATED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "child_task_id": child,
                "tool_name": "agent.research",
                "tool_call_id": tool_call,
                "arguments": {
                    "objective": "Collect evidence",
                    "delegation_reason": "Isolate the bounded research",
                },
                "assistant_message": "Delegating research.",
                "conversation": [],
                "model_calls_used": 7,
                "tool_calls_executed": 11,
            },
            created_at=now,
        ),
        SessionEvent.create(
            session_id=parent,
            sequence=1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.HARNESS,
            payload={
                "command_id": str(uuid4()),
                "session_id": str(parent),
                "kind": "resume",
                "expected_revision": 0,
                "idempotency_key": f"child-wakeup:{parent}",
                "payload": {
                    "child_results": [
                        {
                            "child_task_id": child,
                            "status": "completed",
                            "summary": "Evidence collected.",
                        }
                    ]
                },
                "fingerprint": "a" * 64,
            },
            created_at=now,
        ),
    ]

    recovered = recover_child_wakeup_continuation(events)

    assert recovered is not None
    assert recovered.model_calls_used == 7
    assert recovered.tool_calls_executed == 11


def test_suspended_child_is_verified_as_failed_terminal_result() -> None:
    assert child_terminal_status(SessionStatus.SUSPENDED) is ChildTerminalStatus.FAILED
    assert canonical_child_terminal_summary(None) == "child reached a terminal status"


def test_child_wakeup_rebases_missing_private_reasoning_as_fresh_evidence() -> None:
    parent = new_session_id()
    child = str(uuid4())
    research_call_id = new_tool_call_id()
    provider_call_id = "call-private"
    now = datetime.now(UTC)
    conversation = [
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.USER,
            content="Research the market.",
            created_at=now,
        ).model_dump(mode="json"),
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="I found public evidence.",
            created_at=now,
            tool_calls=(
                ToolCall(
                    tool_call_id=research_call_id,
                    name="events.search_history",
                    arguments={"query": "market"},
                    created_at=now,
                    provider_call_id=provider_call_id,
                ),
            ),
            metadata={"provider_reasoning_required": True},
            provider_reasoning_content="private chain",
        ).model_dump(mode="json"),
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.TOOL,
            content="market evidence",
            created_at=now,
            tool_call_id=provider_call_id,
        ).model_dump(mode="json"),
    ]
    delegated_call_id = str(uuid4())
    events = [
        SessionEvent.create(
            session_id=parent,
            sequence=0,
            event_type=EventType.SUBAGENT_DELEGATED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "child_task_id": child,
                "tool_name": "agent.research",
                "tool_call_id": delegated_call_id,
                "arguments": {"objective": "Verify evidence"},
                "assistant_message": "Delegating research.",
                "conversation": conversation,
                "model_calls_used": 2,
                "tool_calls_executed": 1,
            },
            created_at=now,
        ),
        SessionEvent.create(
            session_id=parent,
            sequence=1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
                actor=EventActor.HARNESS,
                payload={
                    "command_id": str(uuid4()),
                    "session_id": str(parent),
                    "kind": "resume",
                    "expected_revision": 0,
                    "idempotency_key": f"child-wakeup:{parent}",
                    "payload": {
                    "child_results": [
                        {
                            "child_task_id": child,
                            "status": "completed",
                            "summary": "verified",
                        }
                        ]
                    },
                    "fingerprint": "b" * 64,
                },
            created_at=now,
        ),
    ]

    recovered = recover_child_wakeup_continuation(events)

    assert recovered is not None
    assert [message.role for message in recovered.conversation] == [
        MessageRole.USER,
        MessageRole.USER,
        MessageRole.USER,
    ]
    assert recovered.conversation[1].content == "Prior public agent note:\nI found public evidence."
    assert recovered.conversation[2].content == "Durable tool evidence:\nmarket evidence"
    assert all(not message.tool_calls for message in recovered.conversation)
    assert all(message.tool_call_id is None for message in recovered.conversation)
    assert recovered.metadata == {
        "cache_boundary_reason": "private_reasoning_not_durable",
        "exact_prefix_message_count": 1,
        "rebased_message_count": 2,
    }


def test_child_wakeup_replays_terminal_children_as_fresh_user_evidence() -> None:
    now = datetime.now(UTC)
    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.research",
        arguments={"objective": "Research"},
        created_at=now,
        provider_call_id="call-research",
    )
    wakeup = ChildWakeupContinuation(
        tool_calls=(call,),
        child_results=(
            ChildResultDelivery(
                child_task_id=str(uuid4()),
                status="completed",
                summary="Verified evidence.",
            ),
        ),
        conversation=(
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.USER,
                content="Research this.",
                created_at=now,
            ),
        ),
        model_calls_used=2,
        tool_calls_executed=1,
        assistant_message="Researching.",
    )

    messages = child_wakeup_evidence_conversation(wakeup)

    assert [message.role for message in messages] == [MessageRole.USER, MessageRole.USER]
    assert "Verified evidence." in messages[-1].content
    assert messages[-1].metadata["durable_child_evidence"] is True
    assert messages[-1].tool_call_id is None


def test_child_wakeup_preserves_provider_safe_delegation_for_terminal_results() -> None:
    parent = new_session_id()
    child = str(uuid4())
    delegated_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.research",
        arguments={"objective": "Research"},
        created_at=datetime.now(UTC),
        provider_call_id="call-delegated",
    )
    now = delegated_call.created_at
    conversation = [
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.USER,
            content="Research this.",
            created_at=now,
        ).model_dump(mode="json"),
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="I will delegate the bounded research.",
            created_at=now,
            tool_calls=(delegated_call,),
        ).model_dump(mode="json"),
    ]
    events = [
        SessionEvent.create(
            session_id=parent,
            sequence=0,
            event_type=EventType.SUBAGENT_DELEGATED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "child_task_id": child,
                "tool_name": delegated_call.name,
                "tool_call_id": str(delegated_call.tool_call_id),
                "provider_call_id": delegated_call.provider_call_id,
                "arguments": delegated_call.arguments,
                "assistant_message": "Delegating research.",
                "conversation": conversation,
                "model_calls_used": 1,
                "tool_calls_executed": 0,
            },
            created_at=now,
        ),
        SessionEvent.create(
            session_id=parent,
            sequence=1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.HARNESS,
            payload={
                "command_id": str(uuid4()),
                "session_id": str(parent),
                "kind": "resume",
                "expected_revision": 0,
                "idempotency_key": f"child-wakeup:{parent}",
                "payload": {
                    "child_results": [
                        {
                            "child_task_id": child,
                            "status": "completed",
                            "summary": "Verified evidence.",
                        }
                    ]
                },
                "fingerprint": "c" * 64,
            },
            created_at=now,
        ),
    ]

    recovered = recover_child_wakeup_continuation(events)

    assert recovered is not None
    messages = list(recovered.conversation)
    for call, result in zip(
        recovered.tool_calls, child_wakeup_tool_results(recovered), strict=True
    ):
        messages.append(
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.TOOL,
                content=result.output,
                created_at=now,
                tool_call_id=call.provider_call_id or str(call.tool_call_id),
            )
        )
    validate_tool_call_pairing(messages)
    assert any(message.tool_calls for message in messages)
    assert recovered.metadata is None
