from typing import NewType
from uuid import UUID, uuid4

SessionId = NewType("SessionId", UUID)
TaskId = NewType("TaskId", UUID)
EventId = NewType("EventId", UUID)
MessageId = NewType("MessageId", UUID)
ToolCallId = NewType("ToolCallId", UUID)
ArtifactId = NewType("ArtifactId", UUID)
CorrelationId = NewType("CorrelationId", UUID)
MemoryId = NewType("MemoryId", UUID)
SubagentId = NewType("SubagentId", UUID)
HandoffId = NewType("HandoffId", UUID)


def new_session_id() -> SessionId:
    return SessionId(uuid4())


def new_task_id() -> TaskId:
    return TaskId(uuid4())


def new_event_id() -> EventId:
    return EventId(uuid4())


def new_message_id() -> MessageId:
    return MessageId(uuid4())


def new_tool_call_id() -> ToolCallId:
    return ToolCallId(uuid4())


def new_artifact_id() -> ArtifactId:
    return ArtifactId(uuid4())


def new_correlation_id() -> CorrelationId:
    return CorrelationId(uuid4())


def new_memory_id() -> MemoryId:
    return MemoryId(uuid4())


def new_subagent_id() -> SubagentId:
    return SubagentId(uuid4())


def new_handoff_id() -> HandoffId:
    return HandoffId(uuid4())
