"""Provider-neutral private input for exact native operation reconciliation."""

import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_core.domain.identifiers import ClientSessionId, TaskId


class ClientPreparationContext(BaseModel):
    """Opaque caller input captured with one native operation.

    The transport validates its own input schema. The native boundary preserves
    this immutable owner/operation context without interpreting its protocol.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    operation_id: UUID
    client_session_id: ClientSessionId
    task_id: TaskId
    run_id: str = Field(min_length=1, max_length=128)
    projection_version: str = Field(min_length=1, max_length=128)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input: dict[str, object]
    previous_run_id: str = Field(min_length=1, max_length=256)

    @field_validator("input")
    @classmethod
    def validate_input_json(cls, value: dict[str, object]) -> dict[str, object]:
        json.dumps(value, allow_nan=False, separators=(",", ":"))
        return value
