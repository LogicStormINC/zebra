"""Verified source intent before publication; no Artifact store or publication certificate."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from agent_core.domain.coverage_contracts import CoverageContract, CoverageRefusedError
from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_persistence import canonical_coverage_bytes, coverage_manifest_bytes
from agent_core.domain.coverage_snapshot import (
    CoveragePage,
    CoveragePageRequest,
    CoveragePart,
    CoverageRecord,
    CoverageSnapshot,
)
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.identifiers import ArtifactId, SessionId

from agent_integrations.coverage_snapshot_artifacts import artifact_id
from agent_integrations.coverage_snapshot_invocation import (
    CoverageInvocation,
    HostCoverageInvoke,
    OperationBudget,
)
from agent_integrations.coverage_snapshot_wire import (
    Descriptor,
    SnapshotWire,
    normalize_page,
    parse,
    parse_snapshot_wire,
    validate_snapshot_provenance,
    verify_manifest,
)
from agent_integrations.host_tools.contracts import HostToolManifest

MAX_BYTES = 32 * 1024 * 1024
MAX_RECORDS = 100000


@dataclass(frozen=True)
class CoverageSnapshotPreparation:
    """Frozen source intent, not a readable Artifact or proof of publication.

    Construction or copying confers no authority. Consumers must verify the full
    run binding, verify_manifest, canonical bytes/ID and fresh authority before
    publication; this type alone certifies none of those checks.
    """

    descriptor: Descriptor
    records: tuple[CoverageRecord, ...]
    manifest_bytes: bytes
    manifest_artifact_id: ArtifactId


class HostCoverageSnapshotSource:
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
        admitted_effect_invoke: HostCoverageInvoke | None = None,
        max_calls: int = 2048,
        max_seconds: float = 60,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session_id = session_id
        self.host = CoverageInvocation(
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

    def _binding(self, snapshot: Descriptor | CoverageSnapshot) -> dict[str, object]:
        binding: dict[str, object] = {
            "host": snapshot.host_id,
            "namespace": snapshot.namespace,
            "workspace": self.host.bound.workspace_ref,
            "history": self.host.resource.resource_id,
            "snapshot": snapshot.snapshot_id,
            "manifest": snapshot.manifest_digest,
            "scope": snapshot.scope_digest,
            "contract": snapshot.contract_digest,
        }
        if self.host.contract is not None and self.host.contract.schema_version == 2:
            binding["source"] = self.host.resource.model_dump(mode="json", by_alias=True)
        return binding

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
        frozen = self.host.contract
        if frozen is not None and contract is not None and frozen != contract:
            raise CoverageRefusedError(Reason.SCOPE_MISMATCH)
        contract = frozen or contract
        wire = (
            parse_snapshot_wire(value, contract)
            if contract is not None and contract.schema_version == 2
            else parse(SnapshotWire, value, Reason.SCOPE_MISMATCH)
        )
        snapshot = wire.snapshot
        validate_snapshot_provenance(
            wire, contract=contract, authority=authority, source_ref=self.host.resource
        )
        if snapshot_id is not None and snapshot.snapshot_id != snapshot_id:
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

    def _collect(
        self, descriptor: Descriptor, authority: HostContextEnvelope, budget: OperationBudget
    ) -> CoverageSnapshotPreparation:
        budget.check()
        maximum = self._maximum(authority)
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
        if len(body) > maximum:
            raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)
        prepared = CoverageSnapshotPreparation(
            descriptor, rows, body, self.manifest_artifact_id(descriptor)
        )
        budget.check()
        self.host.authority_check(authority)
        self._live(descriptor)
        return prepared

    def _create_budget(
        self, authority: HostContextEnvelope, idempotency_key: str
    ) -> OperationBudget:
        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
            or len(idempotency_key) > 512
        ):
            raise CoverageRefusedError(Reason.UNSUPPORTED)
        return self.host.budget(authority)

    def _create_descriptor(
        self,
        contract: CoverageContract,
        *,
        authority: HostContextEnvelope,
        idempotency_key: str,
        budget: OperationBudget,
    ) -> Descriptor:
        if contract.schema_version == 2 and self.host.contract != contract:
            raise CoverageRefusedError(Reason.SCOPE_MISMATCH)
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
        return self._descriptor(value, authority, contract=contract)

    def _get_descriptor(
        self, snapshot_id: str, authority: HostContextEnvelope, budget: OperationBudget
    ) -> Descriptor:
        if (
            not isinstance(snapshot_id, str)
            or not snapshot_id
            or snapshot_id != snapshot_id.strip()
            or len(snapshot_id) > 256
        ):
            raise CoverageRefusedError(Reason.SCOPE_MISMATCH)
        value = self.host.call("get", {"snapshot_id": snapshot_id}, authority, budget)
        return self._descriptor(value, authority, snapshot_id)

    def create(
        self, contract: CoverageContract, *, authority: HostContextEnvelope, idempotency_key: str
    ) -> CoverageSnapshotPreparation:
        budget = self._create_budget(authority, idempotency_key)
        descriptor = self._create_descriptor(
            contract, authority=authority, idempotency_key=idempotency_key, budget=budget
        )
        return self._collect(descriptor, authority, budget)

    def get(
        self, snapshot_id: str, *, authority: HostContextEnvelope
    ) -> CoverageSnapshotPreparation:
        budget = self.host.budget(authority)
        descriptor = self._get_descriptor(snapshot_id, authority, budget)
        return self._collect(descriptor, authority, budget)

    def get_descriptor(self, snapshot_id: str, *, authority: HostContextEnvelope) -> Descriptor:
        """Revalidate current Host authority without enumerating immutable parts."""
        budget = self.host.budget(authority)
        descriptor = self._get_descriptor(snapshot_id, authority, budget)
        self.host.publication_time(authority, budget, descriptor.as_of, descriptor.expires_at)
        return descriptor
