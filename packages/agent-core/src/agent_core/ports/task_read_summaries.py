"""Watermarked derived Task usage and immutable indexed attachment reads."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agent_core.domain.attachments import SessionAttachmentRef
from agent_core.domain.identifiers import SessionId, TaskId


def _position(value: int, minimum: int = -1) -> None:
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise ValueError("invalid Task summary coordinate")


@dataclass(frozen=True, slots=True)
class TaskReadSummary:
    task_id: TaskId
    through_sequence: int
    highwater: int
    model_usage: dict[str, object] | None
    attachment_count: int
    attachment_bytes: int
    active_segment_id: SessionId | None = None
    turn_fields: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, UUID):
            raise ValueError("invalid Task summary identity")
        _position(self.through_sequence)
        _position(self.highwater)
        _position(self.attachment_count, 0)
        _position(self.attachment_bytes, 0)
        if self.through_sequence > self.highwater:
            raise ValueError("Task summary frontier exceeds canonical highwater")
        if self.active_segment_id is not None and not isinstance(self.active_segment_id, UUID):
            raise ValueError("invalid Task summary Segment identity")

    @property
    def complete(self) -> bool:
        return self.through_sequence == self.highwater


@dataclass(frozen=True, slots=True)
class TaskAttachmentEntry:
    ordinal: int
    task_sequence: int
    attachment: SessionAttachmentRef

    def __post_init__(self) -> None:
        _position(self.ordinal, 0)
        _position(self.task_sequence, 0)


@dataclass(frozen=True, slots=True)
class TaskAttachmentPage:
    task_id: TaskId
    through_sequence: int
    after_ordinal: int
    total_count: int
    total_bytes: int
    entries: tuple[TaskAttachmentEntry, ...]
    byte_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, UUID):
            raise ValueError("invalid Task attachment identity")
        _position(self.through_sequence)
        _position(self.after_ordinal)
        _position(self.total_count, 0)
        _position(self.total_bytes, 0)
        if self.after_ordinal >= self.total_count:
            raise ValueError("attachment cursor exceeds captured coverage")
        if type(self.byte_count) is not int or not 0 <= self.byte_count <= 1_048_576:
            raise ValueError("attachment page exceeds byte budget")
        if len(self.entries) > 256:
            raise ValueError("attachment page exceeds count budget")
        for ordinal, entry in enumerate(self.entries, self.after_ordinal + 1):
            if entry.ordinal != ordinal or ordinal >= self.total_count:
                raise ValueError("attachment page has missing or conflicting coverage")
            if entry.task_sequence > self.through_sequence:
                raise ValueError("attachment page exceeds captured source window")
        if not self.entries and self.after_ordinal < self.total_count - 1:
            raise ValueError("attachment page omits captured coverage")

    @property
    def next_ordinal(self) -> int:
        return self.entries[-1].ordinal if self.entries else self.after_ordinal

    @property
    def has_more(self) -> bool:
        return self.next_ordinal < self.total_count - 1


class TaskReadSummaryPort(Protocol):
    def read_task_summary(self, task_id: TaskId) -> TaskReadSummary | None:
        """Read a single persisted prefix and captured source highwater; never repair."""
        ...

    def read_attachment_page(
        self,
        task_id: TaskId,
        after_ordinal: int = -1,
        *,
        through_sequence: int | None = None,
        limit: int = 256,
        max_bytes: int = 1_048_576,
    ) -> TaskAttachmentPage:
        """Seek metadata first, then only admitted refs; freeze through_sequence on resume."""
        ...

    def backfill_read_summary(
        self, task_id: TaskId, *, limit: int = 256, max_bytes: int = 1_048_576
    ) -> bool:
        """Explicit bounded derivation only; atomically persist rows and their watermark."""
        ...
