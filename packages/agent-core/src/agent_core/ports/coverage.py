"""Snapshot/commit boundaries composed explicitly; no default successful adapter."""

from typing import Protocol, Self

from pydantic import Field, model_validator

from agent_core.domain.coverage_contracts import (
    CoverageArtifactRef,
    CoverageContract,
    CoverageDigest,
    CoverageModel,
    CoverageName,
    CoverageTime,
)
from agent_core.domain.coverage_snapshot import (
    CoveragePage,
    CoveragePageRequest,
    CoveragePart,
    CoveragePartRead,
    CoverageRecord,
    CoverageSnapshot,
)
from agent_core.domain.coverage_validation import AcceptedCoverageUnit, result_set_digest
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.leases import LeaseFence


class CoverageCommit(CoverageModel):
    """Accepted batch intent: Artifact must exist before fenced atomic commit."""

    namespace: CoverageName
    session_id: SessionId
    task_id: TaskId
    run_id: CoverageName
    snapshot_id: CoverageName
    contract_digest: CoverageDigest
    manifest_digest: CoverageDigest
    commit_key: CoverageName
    result_artifact_ref: CoverageArtifactRef
    result_artifact_digest: CoverageDigest
    results: tuple[AcceptedCoverageUnit, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_results(self) -> Self:
        if len({result.key for result in self.results}) != len(self.results):
            raise ValueError("a commit cannot contain duplicate units")
        if self.result_artifact_digest != result_set_digest(self.results):
            raise ValueError("result Artifact digest must bind the canonical batch")
        return self


class CoverageCommitReceipt(CoverageModel):
    namespace: CoverageName
    run_id: CoverageName
    commit_key: CoverageName
    result_artifact_digest: CoverageDigest
    event_watermark: int = Field(strict=True, ge=1)
    committed_at: CoverageTime


class CoverageSnapshotPort(Protocol):
    """Adapters enforce live Host authority and signed, scope-bound cursors.

    Create uses the existing Effect idempotency path. Read calls revalidate
    authority/expiry and immutable bytes. Unsupported profiles raise
    CoverageRefusedError(UNSUPPORTED); an empty snapshot is never a fallback.
    """

    def create(
        self,
        contract: CoverageContract,
        *,
        authority: HostContextEnvelope,
        idempotency_key: str,
    ) -> CoverageSnapshot: ...

    def get(
        self,
        snapshot_id: str,
        *,
        authority: HostContextEnvelope,
    ) -> CoverageSnapshot: ...

    def page(
        self,
        request: CoveragePageRequest,
        *,
        authority: HostContextEnvelope,
    ) -> CoveragePage: ...

    def read(
        self,
        snapshot: CoverageSnapshot,
        record: CoverageRecord,
        part: CoveragePart,
        *,
        authority: HostContextEnvelope,
    ) -> CoveragePartRead: ...


class CoverageCommitPort(Protocol):
    """Atomic Event + derived projection + scheduling intent under the lease.

    Confirm the immutable Artifact is readable, then check current task/run,
    snapshot bindings and fence in the Event transaction. The same commit key
    and digest return the original receipt; a changed digest or stale fence
    must fail. A projection-only update does not implement this Port.
    """

    def commit(
        self,
        request: CoverageCommit,
        *,
        fence: LeaseFence,
    ) -> CoverageCommitReceipt: ...
