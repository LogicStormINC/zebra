"""Immutable storage intents; construction does not confer Host authority."""

import json
from hashlib import sha256
from typing import Self

from pydantic import model_validator

from agent_core.domain.coverage_contracts import (
    CoverageContract,
    CoverageDigest,
    CoverageModel,
    CoverageName,
)
from agent_core.domain.coverage_snapshot import CoverageRecord, CoverageSnapshot
from agent_core.domain.coverage_validation import AcceptedCoverageUnit, manifest_digest
from agent_core.domain.identifiers import SessionId, TaskId


def canonical_coverage_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def coverage_manifest_bytes(records: tuple[CoverageRecord, ...]) -> bytes:
    return canonical_coverage_bytes({
        "schema": "coverage-records/1",
        "records": [record.model_dump(mode="json") for record in records],
    })


def coverage_result_bytes(results: tuple[AcceptedCoverageUnit, ...]) -> bytes:
    from agent_core.domain.coverage_contracts import coverage_digest

    return canonical_coverage_bytes({
        "schema": "coverage-results/1",
        "results": sorted(
            (result.model_dump(mode="json") for result in results), key=coverage_digest
        ),
    })


class CoverageRunBinding(CoverageModel):
    """Bounded Event descriptor; the record manifest lives in a governed Artifact."""

    namespace: CoverageName
    session_id: SessionId
    task_id: TaskId
    run_id: CoverageName
    contract: CoverageContract
    snapshot: CoverageSnapshot
    manifest_artifact_digest: CoverageDigest

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if (
            self.snapshot.namespace != self.namespace
            or self.snapshot.contract_digest != self.contract.digest
            or self.snapshot.scope_digest != self.contract.scope.digest
        ):
            raise ValueError("run binding disagrees with snapshot scope")
        return self

    def verify_manifest(self, payload: bytes) -> tuple[CoverageRecord, ...]:
        if sha256(payload).hexdigest() != self.manifest_artifact_digest:
            raise ValueError("manifest Artifact bytes changed")
        data = json.loads(payload)
        if not isinstance(data, dict) or set(data) != {"schema", "records"}:
            raise ValueError("invalid manifest Artifact schema")
        if data["schema"] != "coverage-records/1" or not isinstance(data["records"], list):
            raise ValueError("invalid manifest Artifact schema")
        records = tuple(CoverageRecord.model_validate(row) for row in data["records"])
        if (
            len(records) != self.snapshot.record_count
            or {row.ordinal for row in records} != set(range(len(records)))
            or len({row.record_id for row in records}) != len(records)
            or manifest_digest(self.contract, records) != self.snapshot.manifest_digest
            or coverage_manifest_bytes(records) != payload
        ):
            raise ValueError("manifest membership or canonical representation disagrees")
        return records
