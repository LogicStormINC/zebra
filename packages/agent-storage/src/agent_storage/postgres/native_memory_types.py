"""Typed results and conflicts for the PostgreSQL-native Memory Gateway."""

from dataclasses import dataclass
from typing import Literal

from agent_core.domain.identifiers import MemoryId

NativeOperation = Literal["publish", "delete"]
NativeResultStatus = Literal["committed", "not_found"]


class NativeMemoryError(RuntimeError):
    """Base error for a native Memory Gateway storage conflict."""


class NativeMemoryConflictError(NativeMemoryError):
    """The operation or memory identity conflicts with committed authority."""


class NativeMemoryStaleGenerationError(NativeMemoryError):
    """The caller supplied an obsolete scope generation."""


class NativeMemoryNamespaceError(ValueError):
    """A request attempted to cross the configured deployment namespace."""


@dataclass(frozen=True, slots=True)
class NativeMemoryMutation:
    memory_id: MemoryId
    operation_id: str
    scope_id: str
    generation: int
    result_status: NativeResultStatus
    replayed: bool


@dataclass(frozen=True, slots=True)
class NativeMemoryOperation:
    operation_id: str
    memory_id: MemoryId
    scope_id: str
    generation: int
    operation: NativeOperation
    result_status: NativeResultStatus


@dataclass(frozen=True, slots=True)
class NativeMemoryReset:
    scope_id: str
    previous_generation: int
    generation: int
    deleted_memories: int


@dataclass(frozen=True, slots=True)
class NativeMemoryRecallHit:
    memory_id: MemoryId
    score: float
    content: str
    memory_type: str
    topic: str
