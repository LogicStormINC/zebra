"""Canonical report format used by the validator, not free-form model delivery."""

from hashlib import sha256
from typing import Literal

from pydantic import ConfigDict, Field

from agent_core.domain.coverage_contracts import CoverageDigest, CoverageModel, coverage_digest
from agent_core.domain.coverage_execution import CoverageObservation
from agent_core.domain.coverage_persistence import CoverageRunBinding, canonical_coverage_bytes
from agent_core.domain.coverage_validation import (
    AcceptedCoverageUnit,
    CoverageCertificate,
    result_set_digest,
)


class CoverageReport(CoverageModel):
    model_config = ConfigDict(frozen=True, extra="forbid", serialize_by_alias=True)
    report_schema: Literal["coverage-report/1"] = Field("coverage-report/1", alias="schema")
    binding_digest: CoverageDigest
    result_set_digest: CoverageDigest
    observations: tuple[CoverageObservation, ...] = Field(max_length=200000)

    def validate_for(
        self, binding: CoverageRunBinding, accepted: tuple[AcceptedCoverageUnit, ...]
    ) -> None:
        if self.binding_digest != coverage_digest(binding.model_dump(mode="json")):
            raise ValueError("report binds a different run or scope")
        if self.result_set_digest != result_set_digest(accepted):
            raise ValueError("report does not bind the exact accepted result set")
        expected = {item.key: item for item in accepted}
        actual = {item.key: item for item in self.observations}
        if len(expected) != len(accepted) or len(actual) != len(self.observations):
            raise ValueError("report contains duplicate identities")
        if set(actual) != set(expected):
            raise ValueError("report omits accepted positive or negative results")
        for key, observation in actual.items():
            if (
                observation.digest != expected[key].result_digest
                or observation.outcome != expected[key].outcome
            ):
                raise ValueError("report observation differs from accepted evidence")

    def validate_certificate(
        self, binding: CoverageRunBinding, certificate: CoverageCertificate, *, watermark: int
    ) -> None:
        accepted = tuple(
            AcceptedCoverageUnit(key=row.key, result_digest=row.digest, outcome=row.outcome)
            for row in self.observations
        )
        self.validate_for(binding, accepted)
        parts = {
            (row.key.record_id, row.key.part_id, row.key.part_digest)
            for row in self.observations
            if row.key.kind == "part"
        }
        expected = {
            "namespace": binding.namespace,
            "host_id": binding.snapshot.host_id,
            "snapshot_id": binding.snapshot.snapshot_id,
            "authority_revision": binding.snapshot.authority_revision,
            "contract_revision": binding.contract.contract_revision,
            "contract_digest": binding.contract.digest,
            "scope_digest": binding.contract.scope.digest,
            "manifest_digest": binding.snapshot.manifest_digest,
            "enumerated_records": binding.snapshot.record_count,
            "read_parts": len(parts),
            "processed_units": len(self.observations),
            "reviewed_units": 0,
            "result_set_digest": self.result_set_digest,
            "aggregate_digest": coverage_digest(self.model_dump(mode="json")),
            "report_digest": sha256(self.canonical_bytes).hexdigest(),
            "validator_version": "exact-artifact/1",
            "event_watermark": watermark,
            "expires_at": binding.snapshot.expires_at,
        }
        if any(getattr(certificate, key) != value for key, value in expected.items()) or not (
            binding.snapshot.as_of <= certificate.created_at < binding.snapshot.expires_at
        ):
            raise ValueError("certificate binding conflicts with authoritative report")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_coverage_bytes(self.model_dump(mode="json"))
