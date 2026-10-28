"""Deployment observations are not execution, shutdown or non-commit authority."""

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BeforeValidator, Field, model_validator

from agent_core.domain.runtime_bundle_types import BundleValue, Digest

CONTRACT_DIGEST = "sha256:e799151daf0e6706309ca1b070a953c0b904166f166686c06e4ea27984fe91e0"

GateUUID = Annotated[
    UUID, BeforeValidator(lambda v: UUID(v) if isinstance(v, str) and str(UUID(v)) == v else v)
]
Revision = Annotated[int, Field(strict=True, ge=0, lt=2**53 - 1)]


class GateCandidate(BundleValue):
    definition_id: GateUUID
    version_id: GateUUID
    release_id: GateUUID
    release_revision: Annotated[int, Field(strict=True, ge=1, lt=2**53)]
    definition_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    bundle_digest: Digest


class GateCommand(BundleValue):
    operation_id: GateUUID
    action: Literal["assess", "drain", "open"]
    expected_revision: Revision
    candidate: GateCandidate | None = None

    @model_validator(mode="after")
    def candidate_shape(self) -> Self:
        if (self.action == "assess") != (self.candidate is not None):
            raise ValueError("assess requires candidate; drain/open do not accept one")
        return self


class GateReceipt(BundleValue):
    operation_id: GateUUID = Field(alias="operationId")
    action: Literal["assess", "drain", "open"]
    input_digest: Digest = Field(alias="inputDigest")
    gate_revision: Annotated[int, Field(strict=True, ge=0, lt=2**53)] = Field(alias="gateRevision")
    admission: Literal["open", "draining"]
    actor: Annotated[str, Field(min_length=1, max_length=128)]
    trust_revision: Annotated[int, Field(strict=True, ge=1, lt=2**53)] = Field(
        alias="trustRevision"
    )


class GateConflict(ValueError):
    """The expected namespace revision no longer authorizes this command."""


class GateState(BundleValue):
    revision: Annotated[int, Field(strict=True, ge=0, lt=2**53)]
    admission: Literal["open", "draining"]

    def apply(self, command: GateCommand) -> "GateState":
        if self.revision != command.expected_revision:
            raise GateConflict("GATE_CAS_CONFLICT")
        if command.action == "assess":
            return self
        return GateState(
            revision=self.revision + 1,
            admission="draining" if command.action == "drain" else "open",
        )


@dataclass(frozen=True)
class GateWork:
    operation_id: str
    fingerprint: str
    candidate_snapshot: dict[str, Any]
    tasks: tuple[dict[str, Any], ...]
    blockers: dict[str, int]

    @property
    def source_complete(self) -> bool:
        return not any(
            self.blockers.get(k, 0)
            for k in ("overflow", "projection_lag", "unbound_tasks", "scope_conflict")
        )


def gate_observation(
    mode: str, blockers: dict[str, int], workers: list[dict[str, Any]], *, source_complete: bool
) -> dict[str, Any]:
    compatible = bool(workers) and all(w["compatible"] for w in workers) and source_complete
    return {
        "proofScope": "canonical_database_observation",
        "admission": mode,
        "checks": {
            "database": "verified",
            "runtimeEngine": (
                "verified"
                if compatible
                and all(w.get("runtimeClass") in {"oci-rootless", "gvisor"} for w in workers)
                else "local_development_only"
                if compatible
                else "unproven"
            ),
            "candidate": "verified" if source_complete else "unproven",
            "workerCompatibility": "compatible" if compatible else "unproven_or_incompatible",
        },
        "qualifiedWorkerObserved": compatible,
        "blockers": blockers,
        "executionQuiescent": mode == "draining" and not any(blockers.values()),
        "fleetCoverage": "not_proven",
        "processesStopped": "not_proven",
        "externalEffectsSettled": "not_proven",
        "safeToStop": False,
        "activationAuthorized": False,
        "workers": workers,
    }
