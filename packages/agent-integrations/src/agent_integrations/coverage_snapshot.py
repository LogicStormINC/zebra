"""Bounded Trench snapshot adapter; runtime/Effect composition is explicit."""

import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime

from agent_core.domain.coverage_contracts import (
    CoverageContract,
    CoverageRefusedError,
)
from agent_core.domain.coverage_contracts import (
    CoverageRefusalReason as Reason,
)
from agent_core.domain.coverage_snapshot import (
    CoveragePage,
    CoveragePageRequest,
    CoveragePart,
    CoveragePartRead,
    CoverageRecord,
    CoverageSnapshot,
)
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_core.ports.coverage import CoverageSnapshotPort

from agent_integrations.coverage_snapshot_artifacts import CoverageArtifacts
from agent_integrations.coverage_snapshot_invocation import (
    HostCoverageInvoke,
    OperationBudget,
)
from agent_integrations.coverage_snapshot_prepared import PreparedCoverageSnapshot
from agent_integrations.coverage_snapshot_read import read_part
from agent_integrations.coverage_snapshot_source import HostCoverageSnapshotSource
from agent_integrations.coverage_snapshot_wire import Descriptor
from agent_integrations.host_tools.contracts import HostToolManifest


class HostCoverageSnapshotAdapter(CoverageSnapshotPort):
    def __init__(
        self,
        *,
        session_id: SessionId,
        authority: HostContextEnvelope,
        history_ref: str | None = None,
        source_ref: HostResourceRef | None = None,
        contract: CoverageContract | None = None,
        manifest: HostToolManifest | None,
        invoke: HostCoverageInvoke | None,
        artifacts: ArtifactPayloadStorePort,
        publication_lock: AbstractContextManager[object],
        admitted_effect_invoke: HostCoverageInvoke | None = None,
        max_calls: int = 2048,
        max_seconds: float = 60,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Share publication_lock across publishers; no multiworker until CAS or single writer."""
        self.session_id = session_id
        self.source = HostCoverageSnapshotSource(
            session_id=session_id,
            authority=authority,
            history_ref=history_ref,
            source_ref=source_ref,
            contract=contract,
            manifest=manifest,
            invoke=invoke,
            admitted_effect_invoke=admitted_effect_invoke,
            max_calls=max_calls,
            max_seconds=max_seconds,
            now=now,
            monotonic=monotonic,
        )
        self.host = self.source.host
        self.artifacts = CoverageArtifacts(artifacts, session_id, publication_lock)

    def manifest_artifact_id(self, snapshot: Descriptor | CoverageSnapshot) -> ArtifactId:
        return self.source.manifest_artifact_id(snapshot)

    def body_artifact_id(
        self, snapshot: CoverageSnapshot, record: CoverageRecord, part: CoveragePart
    ) -> ArtifactId:
        return self.source.body_artifact_id(snapshot, record, part)

    def _maximum(self, authority: HostContextEnvelope) -> int:
        return self.source._maximum(authority)

    def _descriptor(
        self,
        value: dict[str, object],
        authority: HostContextEnvelope,
        snapshot_id: str | None = None,
        contract: CoverageContract | None = None,
    ) -> Descriptor:
        return self.source._descriptor(value, authority, snapshot_id, contract)

    def _live(self, snapshot: Descriptor | CoverageSnapshot) -> None:
        self.source._live(snapshot)

    def _page(
        self, request: CoveragePageRequest, authority: HostContextEnvelope, budget: OperationBudget
    ) -> CoveragePage:
        return self.source._page(request, authority, budget)

    def _resolve(
        self, descriptor: Descriptor, authority: HostContextEnvelope, budget: OperationBudget
    ) -> tuple[CoverageSnapshot, tuple[CoverageRecord, ...]]:
        budget.check()
        identifier = self.manifest_artifact_id(descriptor)
        maximum = self._maximum(authority)
        stored = self.artifacts.manifest(identifier, descriptor, maximum, self.host.now())
        if stored is None:
            prepared = self.source._collect(descriptor, authority, budget)
            rows = prepared.records
            body = prepared.manifest_bytes
            uri = self.artifacts.publish(
                identifier,
                "coverage_manifest",
                body,
                maximum,
                lambda: self.host.publication_time(
                    authority, budget, descriptor.as_of, descriptor.expires_at
                ),
                descriptor.expires_at,
            )
        else:
            uri, rows = stored
        budget.check()
        self.host.authority_check(authority)
        self._live(descriptor)
        return CoverageSnapshot(
            **descriptor.model_dump(),
            manifest_artifact_ref=uri,
            source_resource_ref=self.host.resource.resource_id,
        ), rows

    def create(
        self, contract: CoverageContract, *, authority: HostContextEnvelope, idempotency_key: str
    ) -> CoverageSnapshot:
        budget = self.source._create_budget(authority, idempotency_key)
        descriptor = self.source._create_descriptor(
            contract, authority=authority, idempotency_key=idempotency_key, budget=budget
        )
        return self._resolve(descriptor, authority, budget)[0]

    def _get(
        self, snapshot_id: str, authority: HostContextEnvelope, budget: OperationBudget
    ) -> tuple[CoverageSnapshot, tuple[CoverageRecord, ...]]:
        descriptor = self.source._get_descriptor(snapshot_id, authority, budget)
        return self._resolve(descriptor, authority, budget)

    def get(self, snapshot_id: str, *, authority: HostContextEnvelope) -> CoverageSnapshot:
        return self._get(snapshot_id, authority, self.host.budget(authority))[0]

    def prepare(
        self, snapshot_id: str, *, authority: HostContextEnvelope
    ) -> PreparedCoverageSnapshot:
        return PreparedCoverageSnapshot(self, snapshot_id, authority)

    def page(self, request: CoveragePageRequest, *, authority: HostContextEnvelope) -> CoveragePage:
        if request.page_size > 100 or request.namespace != authority.namespace_id:
            raise CoverageRefusedError(Reason.SCOPE_MISMATCH)
        budget = self.host.budget(authority)
        snapshot, rows = self._get(request.snapshot_id, authority, budget)
        if request.scope_digest != snapshot.scope_digest:
            raise CoverageRefusedError(Reason.SCOPE_MISMATCH)
        page = self._page(request, authority, budget)
        if page.records:
            start = page.records[0].ordinal
            if (
                page.records != rows[start : start + len(page.records)]
                or (request.cursor is None and start != 0)
                or ((start + len(page.records) == len(rows)) != (page.next_cursor is None))
            ):
                raise CoverageRefusedError(Reason.MANIFEST_MISMATCH)
        elif snapshot.record_count:
            raise CoverageRefusedError(Reason.MANIFEST_MISMATCH)
        self._live(snapshot)
        budget.check()
        return page

    def read(
        self,
        snapshot: CoverageSnapshot,
        record: CoverageRecord,
        part: CoveragePart,
        *,
        authority: HostContextEnvelope,
    ) -> CoveragePartRead:
        return read_part(self, snapshot, record, part, authority)
