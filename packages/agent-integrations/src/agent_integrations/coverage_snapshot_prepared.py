"""One bounded batch's verified index; never a replacement for live Host checks."""

from typing import TYPE_CHECKING

from agent_core.domain.artifact_payloads import ArtifactPayloadStatus
from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_snapshot import CoveragePart, CoveragePartRead, CoverageRecord
from agent_core.domain.host_authority import HostContextEnvelope

from agent_integrations.coverage_snapshot_read import read_part

if TYPE_CHECKING:
    from agent_integrations.coverage_snapshot import HostCoverageSnapshotAdapter


class PreparedCoverageSnapshot:
    def __init__(
        self,
        adapter: "HostCoverageSnapshotAdapter",
        snapshot_id: str,
        authority: HostContextEnvelope,
    ) -> None:
        self._adapter = adapter
        self._authority = authority
        self.snapshot, self.records = adapter._get(
            snapshot_id, authority, adapter.host.budget(authority)
        )
        self._identifier = adapter.manifest_artifact_id(self.snapshot)
        self._metadata = adapter.artifacts.store.inspect_payload(self._identifier)
        if self._metadata is None or self._metadata.status != ArtifactPayloadStatus.AVAILABLE:
            raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)

    def read(self, record: CoverageRecord, part: CoveragePart) -> CoveragePartRead:
        adapter = self._adapter
        budget = adapter.host.budget(self._authority)
        value = adapter.host.call(
            "get", {"snapshot_id": self.snapshot.snapshot_id}, self._authority, budget
        )
        descriptor = adapter._descriptor(value, self._authority, self.snapshot.snapshot_id)
        if (
            self.snapshot.source_resource_ref != adapter.host.resource.resource_id
            or descriptor.model_dump()
            != self.snapshot.model_dump(exclude={"manifest_artifact_ref", "source_resource_ref"})
        ):
            raise CoverageRefusedError(Reason.SCOPE_MISMATCH)
        if adapter.artifacts.store.inspect_payload(self._identifier) != self._metadata:
            raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)
        return read_part(
            adapter,
            self.snapshot,
            record,
            part,
            self._authority,
            verified=(self.snapshot, self.records),
            budget=budget,
        )
