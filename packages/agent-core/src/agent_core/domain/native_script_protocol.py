"""Closed wire frames and parent-generated observations; never Coverage proof."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator

from agent_core.domain.native_script import ScriptValue
from agent_core.domain.runtime_bundle_types import Digest


class ScriptInvocation(ScriptValue):
    abi: Literal["cloud-agent.native-script/1"]
    invocation_id: str
    manifest_digest: Digest
    arguments: dict[str, str | int | bool]

    @field_validator("invocation_id")
    @classmethod
    def canonical_uuid(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("canonical invocation UUID required")
        return value


class ScriptResponse(ScriptValue):
    abi: Literal["cloud-agent.native-script/1"]
    invocation_id: str
    manifest_digest: Digest
    output: dict[str, str | int | bool]


class ScriptObservation(ScriptValue):
    abi: Literal["cloud-agent.native-script/1"]
    invocation_id: str
    manifest_digest: Digest
    input_digest: Digest
    runtime_spec_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    status: Literal["succeeded", "failed"]
    reason: Literal["ok", "timeout", "process_failed", "output_limit", "invalid_response"]
    output_digest: Digest | None


@dataclass(frozen=True)
class ScriptRunResult:
    observation: ScriptObservation
    output_json: bytes | None

    def __post_init__(self) -> None:
        if self.observation.status == "succeeded":
            if (
                self.output_json is None
                or self.observation.reason != "ok"
                or self.observation.output_digest
                != "sha256:" + sha256(self.output_json).hexdigest()
            ):
                raise ValueError("success requires bound output")
        elif self.output_json is not None or self.observation.output_digest is not None:
            raise ValueError("failure must not expose output")
