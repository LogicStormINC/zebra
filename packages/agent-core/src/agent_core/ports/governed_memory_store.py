from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.governed_memories import (
    GovernedMemoryEntry,
    GovernedMemoryManagementContext,
    GovernedMemoryTombstone,
)
from agent_core.domain.governed_memory_operations import (
    AdministrativeMemoryReviewRequest,
    WorkerMemoryMutationPlan,
)
from agent_core.domain.governed_memory_receipts import GovernedMemoryCommitResult
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryVisibility,
)
from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS, WorkerMutationAuthority


class GovernedMemoryScanCursor(BaseModel):
    """Opaque continuation bound to the logical snapshot created on the first page."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_token: str = Field(max_length=512)
    position_token: str = Field(max_length=2048)

    @field_validator("snapshot_token", "position_token")
    @classmethod
    def require_opaque_token(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("scan cursor tokens must be non-blank and trimmed")
        return value


class GovernedMemoryScanQuery(BaseModel):
    """Management-only complete scan of one exact confirmed Memory scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: MemoryQuery
    cursor: GovernedMemoryScanCursor | None = None
    limit: int = Field(default=200, ge=1, le=500)

    @model_validator(mode="after")
    def require_confirmed_exact_scope(self) -> "GovernedMemoryScanQuery":
        if self.scope.statuses != (MemoryStatus.CONFIRMED,):
            raise ValueError("authority scan is limited to confirmed Memory")
        if self.scope.text_query is not None or self.scope.source_session_id is not None:
            raise ValueError("authority scan rejects text and source Session filters")
        if self.scope.visibility is None:
            raise ValueError("authority scan requires exact visibility")
        expected_scope = {
            MemoryVisibility.REPO: (self.scope.repo_id, self.scope.user_id, self.scope.tenant_id),
            MemoryVisibility.USER: (self.scope.user_id, self.scope.repo_id, self.scope.tenant_id),
            MemoryVisibility.TENANT: (self.scope.tenant_id, self.scope.repo_id, self.scope.user_id),
        }[self.scope.visibility]
        if expected_scope[0] is None or any(expected_scope[1:]):
            raise ValueError("authority scan requires exactly one visibility-matching scope")
        return self


class GovernedMemoryScanPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[GovernedMemoryEntry, ...]
    next_cursor: GovernedMemoryScanCursor | None = None


class GovernedMemoryStorePort(Protocol):
    """Namespace-bound authoritative cloud Memory store."""

    def get(self, memory_id: MemoryId) -> MemoryRecord | None: ...

    def list(self, query: MemoryQuery) -> list[MemoryRecord]: ...

    def list_for_worker(
        self,
        query: MemoryQuery,
        *,
        authority: WorkerMutationAuthority,
    ) -> tuple[GovernedMemoryEntry, ...]:
        """Read revisioned authority for a fenced Worker mutation plan."""
        ...

    def get_authority(
        self,
        memory_id: MemoryId,
        *,
        management: GovernedMemoryManagementContext,
    ) -> GovernedMemoryEntry | GovernedMemoryTombstone | None: ...

    def commit_worker_candidates(
        self,
        plan: WorkerMemoryMutationPlan,
        *,
        authority: WorkerMutationAuthority,
    ) -> GovernedMemoryCommitResult: ...

    def commit_administrative_review(
        self,
        request: AdministrativeMemoryReviewRequest,
        *,
        authority: AdministrativeMutationCAS,
    ) -> GovernedMemoryCommitResult: ...

    def scan_confirmed(
        self,
        query: GovernedMemoryScanQuery,
        *,
        management: GovernedMemoryManagementContext,
    ) -> GovernedMemoryScanPage:
        """Continue only within the logical snapshot identified by the first-page cursor."""
        ...
