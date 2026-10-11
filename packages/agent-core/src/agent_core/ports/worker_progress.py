"""Run-scoped execution progress, independent of UI projection checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agent_core.domain.identifiers import EventId, TaskId
from agent_core.ports.model_commentary_progress import PendingModelCommentary

if TYPE_CHECKING:
    from agent_core.ports.agent_tasks import TaskEventPage

MAX_PROGRESS_STATE_BYTES = 32_768
MAX_PROGRESS_KEY_BYTES = 262_144
PROGRESS_VERSION = "worker-progress-v1"


@dataclass(frozen=True, slots=True)
class WorkerProgressScope:
    namespace: str
    task_id: TaskId
    run_id: str
    anchor_event_id: EventId
    anchor_sequence: int
    version: str = PROGRESS_VERSION

    def __post_init__(self) -> None:
        for value, maximum in ((self.namespace, 256), (self.run_id, 256), (self.version, 64)):
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value.encode("utf-8")) > maximum
                or any(ord(char) < 32 for char in value)
            ):
                raise ValueError("invalid Worker progress scope")
        if not isinstance(self.task_id, UUID) or not isinstance(self.anchor_event_id, UUID):
            raise ValueError("invalid Worker progress identity")
        if type(self.anchor_sequence) is not int or not 0 <= self.anchor_sequence < 2**63:
            raise ValueError("invalid Worker progress Run anchor")


class WorkerProgressState(BaseModel):
    """Small scalar state; output and receipt membership stay in indexed rows."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    policy_json: str | None = Field(default=None, max_length=4096)
    chinese: bool | None = None
    attempt_number: int = Field(default=1, ge=1, lt=2**63)
    attempt_started: bool = False
    model_spoke: bool = False
    started: bool = False
    meaningful: bool = False
    evidence_published: bool = False
    result_published: bool = False
    expression_calls_used: int = Field(default=0, ge=0, lt=2**63)
    published_count: int = Field(default=0, ge=0, le=128)
    commentary_reserved_count: int = Field(default=0, ge=0, le=8)
    commentary_published_count: int = Field(default=0, ge=0, le=8)
    pending_commentary: PendingModelCommentary | None = None
    terminal: bool = False


@dataclass(frozen=True, slots=True)
class WorkerProgressHead:
    scope: WorkerProgressScope
    through_sequence: int
    last_event_id: EventId | None
    state: WorkerProgressState

    def __post_init__(self) -> None:
        if type(self.through_sequence) is not int or not (
            self.scope.anchor_sequence - 1 <= self.through_sequence < 2**63
        ):
            raise ValueError("invalid Worker progress frontier")
        initial = self.through_sequence == self.scope.anchor_sequence - 1
        if initial != (self.last_event_id is None) or (
            self.last_event_id is not None and not isinstance(self.last_event_id, UUID)
        ):
            raise ValueError("Worker progress frontier identity disagrees")
        if not isinstance(self.state, WorkerProgressState):
            raise TypeError("Worker progress requires typed state")


def validate_progress_keys(keys: tuple[str, ...], *, limit: int = 32) -> None:
    if type(keys) is not tuple or len(keys) > limit:
        raise ValueError("Worker progress key batch exceeds count bound")
    total = 0
    for key in keys:
        if (
            not isinstance(key, str)
            or not key.strip()
            or len(key) > 2048
            or any(ord(char) < 32 for char in key)
        ):
            raise ValueError("invalid Worker progress key")
        total += len(key.encode("utf-8")) + 128
    if total > MAX_PROGRESS_KEY_BYTES:
        raise ValueError("Worker progress key batch exceeds byte bound")


class WorkerProgressPort(Protocol):
    """Derived-only state, with canonical Run validation and atomic frontier CAS.

    Missing state is not-ready, never an implicit historical scan. Advancement is
    explicit maintenance over a previously admitted canonical page. All reads
    and writes are namespace-scoped. Membership reads have bounded key batches.
    """

    def read_worker_progress(self, scope: WorkerProgressScope) -> WorkerProgressHead: ...

    def advance_worker_progress(
        self, scope: WorkerProgressScope, page: TaskEventPage
    ) -> WorkerProgressHead: ...

    def worker_output_published(self, scope: WorkerProgressScope, output_id: str) -> bool: ...

    def worker_receipts_covered(
        self, scope: WorkerProgressScope, references: tuple[str, ...]
    ) -> frozenset[str]: ...
