"""A proof about one gate command; never Task, process or fleet termination."""

from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from agent_core.domain.runtime_bundle_json import load_bundle_json
from agent_core.domain.runtime_bundle_types import BundleValue, Digest
from agent_core.domain.runtime_gates import GateCommand, GateReceipt, GateUUID, Revision

CONTRACT_DIGEST = "sha256:e4c73f0a55fda8d4d69ee936d6108e00a2d08c5dafe37be27cadb48162858954"


class GateTerminationCommand(BundleValue):
    termination_id: GateUUID
    original_request: Annotated[str, Field(min_length=1, max_length=16384)]
    expected_gate_revision: Revision

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if len(self.original_request.encode()) > 16384:
            raise ValueError("ORIGINAL_TOO_LARGE")
        if self.original.operation_id == self.termination_id:
            raise ValueError("DISTINCT_TERMINATION_ID_REQUIRED")
        return self

    @property
    def original(self) -> GateCommand:
        return GateCommand.model_validate(load_bundle_json(self.original_request.encode()))

    @property
    def original_digest(self) -> str:
        return "sha256:" + sha256(self.original_request.encode()).hexdigest()


class GateTerminationReceipt(BundleValue):
    termination_id: GateUUID = Field(alias="terminationId")
    operation_id: GateUUID = Field(alias="operationId")
    input_digest: Digest = Field(alias="inputDigest")
    original_input_digest: Digest = Field(alias="originalInputDigest")
    outcome: Literal["no_gate_commit", "already_committed"]
    gate_revision: Annotated[int, Field(strict=True, ge=0, lt=2**53)] = Field(alias="gateRevision")
    actor: Annotated[str, Field(min_length=1, max_length=128)]
    trust_revision: Annotated[int, Field(strict=True, ge=1, lt=2**53)] = Field(
        alias="trustRevision"
    )
    late_submission_fenced: Literal[True] = Field(alias="lateSubmissionFenced")
    proof_scope: Literal["original_gate_command_only"] = Field(alias="proofScope")
    original: GateReceipt | None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (self.outcome == "already_committed") != (self.original is not None):
            raise ValueError("INVALID_TERMINATION_PROOF")
        if self.original is not None and (
            self.original.operation_id != self.operation_id
            or self.original.input_digest != self.original_input_digest
            or self.gate_revision < self.original.gate_revision
        ):
            raise ValueError("ORIGINAL_MISMATCH")
        return self
