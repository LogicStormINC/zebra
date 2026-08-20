"""Atomic Task admission contract (AL-TASK-ADMISSION-PG-01, ADR-017 §5).

Admission writes the root Session, bootstrap Events, both projections, the
Agent Task row with its event index, the immutable Task binding snapshot and
the idempotency receipt inside ONE PostgreSQL transaction. Manifest fetches
happen before this call, outside the transaction. Any failure rolls the
whole admission back — a Task is either fully accepted or not present.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import Session
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.idempotency_store import IdempotencyRecord


@dataclass(frozen=True, slots=True)
class TaskAdmissionRequest:
    """Every object a Task admission must persist atomically."""

    events: tuple[SessionEvent, ...]
    session: Session
    workspace: WorkspaceProjection
    binding: TaskBindingSnapshot | None = None
    idempotency: IdempotencyRecord | None = None

    def validate(self) -> None:
        if not self.events:
            raise ValueError("task admission requires bootstrap events")
        root = self.events[0].session_id
        if self.session.session_id != root:
            raise ValueError("task admission session must match its bootstrap events")
        for event in self.events:
            if event.session_id != root:
                raise ValueError("bootstrap events must belong to one root Session")
        if self.binding is not None and str(self.binding.task_id) != str(root):
            raise ValueError("task binding must reference the admitted Task")


@dataclass(frozen=True, slots=True)
class TaskAdmissionReceipt:
    """Result of one atomic admission."""

    task_id: TaskId
    session_id: SessionId
    event_count: int
    binding_digest: str | None
    idempotent_replay: bool = False
    replayed_record: IdempotencyRecord | None = None


class TaskAdmissionIdempotencyConflict(ValueError):
    """The idempotency key was reused with a different canonical request."""


class TaskAdmissionTransactionPort(Protocol):
    """Persist one Task admission atomically or not at all."""

    def admit(self, request: TaskAdmissionRequest) -> TaskAdmissionReceipt: ...
