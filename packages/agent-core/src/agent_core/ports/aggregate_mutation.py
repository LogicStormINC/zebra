from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence


class _SessionMutationCAS(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    deployment_namespace: str = Field(max_length=255)
    session_id: SessionId
    expected_stream_revision: int = Field(ge=-1)

    @field_validator("deployment_namespace")
    @classmethod
    def require_canonical_namespace(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("deployment namespace must be non-blank and trimmed")
        return value


class WorkerMutationAuthority(_SessionMutationCAS):
    """Authority an aggregate adapter must validate inside its write transaction."""

    lease_fence: LeaseFence


class AdministrativeMutationCAS(_SessionMutationCAS):
    """Non-Worker CAS for an administrative mutation outside an active execution."""
