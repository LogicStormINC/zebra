from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.governed_memories import GovernedMemoryEntry
from agent_core.domain.identifiers import SessionId
from agent_core.domain.memories import MemoryQuery, MemoryStatus
from agent_core.domain.session_history import SessionHistoryMessage

MAX_CONTEXT_HISTORY_MESSAGES = 100
MAX_CONTEXT_MEMORY_ENTRIES = 50


class ContextMaterializationMode(StrEnum):
    INITIAL = "initial"
    CONTINUE = "continue"
    RECOVERY = "recovery"


@dataclass(frozen=True)
class ContextMaterializationRequest:
    """Trusted read inputs for one ephemeral Context generation."""

    scope: OpaqueAuthorityScope
    session_id: SessionId
    expected_session_revision: int
    as_of: datetime
    mode: ContextMaterializationMode = ContextMaterializationMode.CONTINUE
    expected_active_capsule_id: str | None = None
    history_limit: int = 20
    memory_query: MemoryQuery | None = None

    def __post_init__(self) -> None:
        if self.expected_session_revision < 0:
            raise ValueError("expected_session_revision must not be negative")
        if not self.scope.allows_session(self.session_id):
            raise ValueError("Context materialization session is outside the read scope")
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if not 1 <= self.history_limit <= MAX_CONTEXT_HISTORY_MESSAGES:
            raise ValueError(f"history_limit must be between 1 and {MAX_CONTEXT_HISTORY_MESSAGES}")
        if self.expected_active_capsule_id is not None:
            if not self.expected_active_capsule_id.strip():
                raise ValueError("expected_active_capsule_id must not be blank")
            object.__setattr__(
                self,
                "expected_active_capsule_id",
                self.expected_active_capsule_id.strip(),
            )
        if self.memory_query is not None:
            if self.memory_query.statuses != (MemoryStatus.CONFIRMED,):
                raise ValueError("Context materialization only recalls confirmed Memory")
            if self.memory_query.limit > MAX_CONTEXT_MEMORY_ENTRIES:
                raise ValueError(f"memory_query.limit must not exceed {MAX_CONTEXT_MEMORY_ENTRIES}")


@dataclass(frozen=True)
class ContextMaterializationGeneration:
    """The durable-source revisions that identify an ephemeral read result."""

    session_revision: int
    active_capsule_id: str | None
    memory_revisions: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if self.session_revision < 0:
            raise ValueError("session_revision must not be negative")
        if self.active_capsule_id is not None:
            if not self.active_capsule_id.strip():
                raise ValueError("active_capsule_id must not be blank")
            if self.active_capsule_id != self.active_capsule_id.strip():
                raise ValueError("active_capsule_id must be trimmed")
        if tuple(sorted(self.memory_revisions)) != self.memory_revisions:
            raise ValueError("memory_revisions must be sorted")
        seen: set[str] = set()
        for memory_id, revision in self.memory_revisions:
            if not memory_id.strip() or memory_id != memory_id.strip() or memory_id in seen:
                raise ValueError("memory_revisions must contain unique non-blank IDs")
            if revision < 1:
                raise ValueError("Memory revisions must be positive")
            seen.add(memory_id)


@dataclass(frozen=True)
class ContextMaterialization:
    """Read-only assembly of History, active Capsule and governed Memory."""

    request: ContextMaterializationRequest
    session_revision: int
    history: tuple[SessionHistoryMessage, ...] = ()
    history_truncated: bool = False
    # When truncation dropped text messages, the newest dropped sequence:
    # everything at or older than this boundary is uncovered unless the
    # active Capsule's source range reaches it (ADR-026 §7).
    truncated_before_sequence: int | None = None
    active_capsule: ContextCapsule | None = None
    memories: tuple[GovernedMemoryEntry, ...] = ()

    def __post_init__(self) -> None:
        if self.session_revision != self.request.expected_session_revision:
            raise ValueError("Context materialization Session revision is stale")
        if len(self.history) > self.request.history_limit:
            raise ValueError("Context materialization history exceeds its limit")
        if self.truncated_before_sequence is not None and not self.history_truncated:
            raise ValueError("truncated_before_sequence requires history_truncated")
        if self.history_truncated and self.truncated_before_sequence is None:
            # Truncation always has a newest-dropped message; without the
            # boundary the prefix coverage cannot be verified (ADR-026 §7).
            raise ValueError("history_truncated requires truncated_before_sequence")
        if (
            self.truncated_before_sequence is not None
            and self.history
            and self.truncated_before_sequence >= self.history[0].sequence
        ):
            raise ValueError("truncated_before_sequence must precede the kept window")
        if self.active_capsule is not None and self.truncated_before_sequence is not None:
            source_range = self.active_capsule.source_event_range
            if source_range is None:
                # A Capsule without a source range cannot prove that it
                # covers the truncated prefix: fail closed.
                raise ValueError(
                    "Context materialization has an active Capsule without a "
                    "source range covering the truncated History prefix"
                )
            if self.truncated_before_sequence > source_range.end_sequence:
                raise ValueError(
                    "Context materialization has an uncovered gap between the "
                    "active Capsule and the kept History window"
                )
        if any(
            previous.sequence >= current.sequence
            for previous, current in zip(self.history, self.history[1:], strict=False)
        ):
            raise ValueError("Context materialization history must be ordered")
        active_id = None if self.active_capsule is None else self.active_capsule.capsule_id
        if active_id != self.request.expected_active_capsule_id:
            raise ValueError("Context materialization active Capsule is stale")
        if len(self.memories) > MAX_CONTEXT_MEMORY_ENTRIES:
            raise ValueError("Context materialization Memory exceeds its limit")
        if self.request.memory_query is None and self.memories:
            raise ValueError("Memory entries require an explicit visibility query")
        seen: set[str] = set()
        for entry in self.memories:
            memory_id = str(entry.record.memory_id)
            if memory_id in seen:
                raise ValueError("Context materialization Memory IDs must be unique")
            seen.add(memory_id)
            if entry.record.status is not MemoryStatus.CONFIRMED:
                raise ValueError("Context materialization accepts confirmed Memory only")
            if (
                entry.record.expires_at is not None
                and entry.record.expires_at <= self.request.as_of
            ):
                raise ValueError("expired Memory cannot enter Context materialization")
            if self.request.memory_query is not None and not _matches_memory_query(
                entry, self.request.memory_query
            ):
                raise ValueError("Memory entry is outside the requested visibility scope")

    @property
    def generation(self) -> ContextMaterializationGeneration:
        return ContextMaterializationGeneration(
            session_revision=self.session_revision,
            active_capsule_id=(
                None if self.active_capsule is None else self.active_capsule.capsule_id
            ),
            memory_revisions=tuple(
                sorted((str(entry.record.memory_id), entry.revision) for entry in self.memories)
            ),
        )


def _matches_memory_query(entry: GovernedMemoryEntry, query: MemoryQuery) -> bool:
    record = entry.record
    return (
        all(
            value is None or getattr(record, field) == value
            for field, value in (
                ("tenant_id", query.tenant_id),
                ("user_id", query.user_id),
                ("repo_id", query.repo_id),
                ("authority_issuer", query.authority_issuer),
                ("namespace_id", query.namespace_id),
                ("definition_id", query.definition_id),
                ("source_session_id", query.source_session_id),
            )
        )
        and (query.visibility is None or record.visibility is query.visibility)
        and (not query.memory_types or record.memory_type in query.memory_types)
    )
