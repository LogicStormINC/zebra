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
from agent_core.domain.coverage_persistence import canonical_coverage_bytes, coverage_manifest_bytes
from agent_core.domain.coverage_snapshot import (
    CoveragePage,
    CoveragePageRequest,
    CoveragePart,
    CoveragePartRead,
    CoverageRecord,
    CoverageSnapshot,
)
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_core.ports.coverage import CoverageSnapshotPort

from agent_integrations.coverage_snapshot_artifacts import CoverageArtifacts, artifact_id
from agent_integrations.coverage_snapshot_invocation import (
    CoverageInvocation,
    HostCoverageInvoke,
    OperationBudget,
)
from agent_integrations.coverage_snapshot_read import read_part
from agent_integrations.coverage_snapshot_wire import (
    Descriptor,
    SnapshotWire,
    normalize_page,
    parse,
    verify_manifest,
)
from agent_integrations.host_tools.contracts import HostToolManifest

MAX_BYTES = 32 * 1024 * 1024
MAX_RECORDS = 100000


class HostCoverageSnapshotAdapter(CoverageSnapshotPort):
    def __init__(
        self,
        *,
        session_id: SessionId,
        authority: HostContextEnvelope,
        history_ref: str,
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
        self.host = CoverageInvocation(
            authority=authority,
            history_ref=history_ref,
            manifest=manifest,
            invoke=invoke,
            admitted_effect_invoke=admitted_effect_invoke,
            max_calls=max_calls,
            max_seconds=max_seconds,
            now=now,
            monotonic=monotonic,
        )
        self.artifacts = CoverageArtifacts(artifacts, session_id, publication_lock)

    def _binding(self, snapshot: Descriptor | CoverageSnapshot) -> dict[str, object]:
        return {
            "host": snapshot.host_id,
            "namespace": snapshot.namespace,
            "workspace": self.host.bound.workspace_ref,
            "history": self.host.resource.resource_id,
            "snapshot": snapshot.snapshot_id,
            "manifest": snapshot.manifest_digest,
            "scope": snapshot.scope_digest,
            "contract": snapshot.contract_digest,
        }

    def manifest_artifact_id(self, snapshot: Descriptor | CoverageSnapshot) -> ArtifactId:
        return artifact_id(self.session_id, {"kind": "manifest", **self._binding(snapshot)})

    def body_artifact_id(
        self, snapshot: CoverageSnapshot, record: CoverageRecord, part: CoveragePart
    ) -> ArtifactId:
        return artifact_id(
            self.session_id,
            {
                "kind": "body",
                **self._binding(snapshot),
                "record": record.model_dump(mode="json"),
                "part": part.model_dump(mode="json"),
            },
        )

    def _maximum(self, authority: HostContextEnvelope) -> int:
        return min(MAX_BYTES, authority.limits.max_artifact_bytes)

    def _descriptor(
        self,
        value: dict[str, object],
        authority: HostContextEnvelope,
        snapshot_id: str | None = None,
        contract: CoverageContract | None = None,
    ) -> Descriptor:
        wire = parse(SnapshotWire, value, Reason.SCOPE_MISMATCH)
        snapshot = wire.snapshot
        if (
            snapshot.namespace != authority.namespace_id
            or snapshot.host_id != authority.host_app_id
            or (snapshot_id is not None and snapshot.snapshot_id != snapshot_id)
            or wire.provenance.history_ref != self.host.resource.resource_id
            or wire.provenance.workspace_ref != authority.workspace_ref
            or wire.provenance.periods_digest != snapshot.authority_revision
            or wire.content_capabilities != ("canonical_body",)
            or wire.scope.digest != snapshot.scope_digest
            or not snapshot.as_of <= wire.sealed_at < snapshot.expires_at
            or (
                contract is not None
                and (wire.scope != contract.scope or snapshot.contract_digest != contract.digest)
            )
        ):
            raise CoverageRefusedError(Reason.SCOPE_MISMATCH)
        self._live(snapshot)
        if snapshot.record_count > MAX_RECORDS:
            raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)
        return snapshot

    def _live(self, snapshot: Descriptor | CoverageSnapshot) -> None:
        if not snapshot.as_of <= self.host.now() < snapshot.expires_at:
            raise CoverageRefusedError(Reason.SNAPSHOT_EXPIRED)

    def _page(
        self, request: CoveragePageRequest, authority: HostContextEnvelope, budget: OperationBudget
    ) -> CoveragePage:
        if request.page_size > 100 or request.namespace != authority.namespace_id:
            raise CoverageRefusedError(Reason.SCOPE_MISMATCH)
        arguments: dict[str, object] = {
            "snapshot_id": request.snapshot_id,
            "page_size": request.page_size,
        }
        if request.cursor is not None:
            arguments["cursor"] = request.cursor
        page = normalize_page(self.host.call("page", arguments, authority, budget))
        page.validate_for(request)
        if not page.records and page.next_cursor is not None:
            raise CoverageRefusedError(Reason.MANIFEST_MISMATCH)
        return page

    def _resolve(
        self, descriptor: Descriptor, authority: HostContextEnvelope, budget: OperationBudget
    ) -> tuple[CoverageSnapshot, tuple[CoverageRecord, ...]]:
        budget.check()
        identifier = self.manifest_artifact_id(descriptor)
        maximum = self._maximum(authority)
        stored = self.artifacts.manifest(identifier, descriptor, maximum, self.host.now())
        if stored is None:
            records: list[CoverageRecord] = []
            ids: set[str] = set()
            cursors: set[str] = set()
            cursor = None
            # Exact canonical envelope bytes, before allocating the complete manifest.
            size = len(coverage_manifest_bytes(()))
            while True:
                self._live(descriptor)
                request = CoveragePageRequest(
                    namespace=descriptor.namespace,
                    snapshot_id=descriptor.snapshot_id,
                    scope_digest=descriptor.scope_digest,
                    page_size=100,
                    cursor=cursor,
                )
                page = self._page(request, authority, budget)
                budget.check()
                if len(records) + len(page.records) > descriptor.record_count:
                    raise CoverageRefusedError(Reason.MANIFEST_MISMATCH)
                for record in page.records:
                    if record.ordinal != len(records) or record.record_id in ids:
                        raise CoverageRefusedError(Reason.MANIFEST_MISMATCH)
                    size += len(canonical_coverage_bytes(record.model_dump(mode="json"))) + bool(
                        records
                    )
                    if size > maximum:
                        raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)
                    ids.add(record.record_id)
                    records.append(record)
                cursor = page.next_cursor
                if cursor is None:
                    break
                if cursor in cursors:
                    raise CoverageRefusedError(Reason.MANIFEST_MISMATCH)
                cursors.add(cursor)
            rows = tuple(records)
            verify_manifest(descriptor, rows)
            budget.check()
            self._live(descriptor)
            body = coverage_manifest_bytes(rows)
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
        return CoverageSnapshot(**descriptor.model_dump(), manifest_artifact_ref=uri), rows

    def create(
        self, contract: CoverageContract, *, authority: HostContextEnvelope, idempotency_key: str
    ) -> CoverageSnapshot:
        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
            or len(idempotency_key) > 512
        ):
            raise CoverageRefusedError(Reason.UNSUPPORTED)
        budget = self.host.budget(authority)
        value = self.host.call(
            "create",
            {
                "scope": contract.scope.model_dump(mode="json"),
                "contract_digest": contract.digest,
                "content_requirements": list(contract.content_requirements),
            },
            authority,
            budget,
            idempotency_key,
        )
        return self._resolve(
            self._descriptor(value, authority, contract=contract), authority, budget
        )[0]

    def _get(
        self, snapshot_id: str, authority: HostContextEnvelope, budget: OperationBudget
    ) -> tuple[CoverageSnapshot, tuple[CoverageRecord, ...]]:
        if (
            not isinstance(snapshot_id, str)
            or not snapshot_id
            or snapshot_id != snapshot_id.strip()
            or len(snapshot_id) > 256
        ):
            raise CoverageRefusedError(Reason.SCOPE_MISMATCH)
        value = self.host.call("get", {"snapshot_id": snapshot_id}, authority, budget)
        return self._resolve(self._descriptor(value, authority, snapshot_id), authority, budget)

    def get(self, snapshot_id: str, *, authority: HostContextEnvelope) -> CoverageSnapshot:
        return self._get(snapshot_id, authority, self.host.budget(authority))[0]

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
