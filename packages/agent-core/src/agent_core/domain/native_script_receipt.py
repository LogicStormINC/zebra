"""Native effect-free invocation state, independent of SQL and transport."""

from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from agent_core.domain.native_script import ScriptValue
from agent_core.domain.native_script_protocol import ScriptObservation, ScriptRunResult
from agent_core.domain.runtime_bundle_types import Digest


class NativeScriptEvent(ScriptValue):
    schema_version: Literal["cloud-agent.native-script-event/1"]
    invocation_id: Annotated[str, Field(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")]
    task_id: Annotated[str, Field(min_length=1, max_length=128)]
    snapshot_digest: Digest
    binding_digest: Digest
    input_digest: Digest
    owner_fence: Digest
    execution_attempt: Annotated[int, Field(ge=1, le=3)]
    phase: Literal["started", "completed"]
    observation: ScriptObservation | None = None
    output_json: Annotated[str, Field(max_length=32_768)] | None = None

    @model_validator(mode="after")
    def result_shape(self) -> Self:
        if self.output_json is not None and len(self.output_json.encode("utf-8")) > 32_768:
            raise ValueError("script receipt output byte limit")
        if self.phase == "started":
            if self.observation is not None or self.output_json is not None:
                raise ValueError("started script cannot claim a result")
        else:
            if self.observation is None or (
                self.observation.invocation_id != self.invocation_id
                or self.observation.input_digest != self.input_digest
            ):
                raise ValueError("script receipt invocation mismatch")
            self.result()
        return self

    def result(self) -> ScriptRunResult:
        if self.observation is None:
            raise ValueError("script receipt is not terminal")
        return ScriptRunResult(
            self.observation, None if self.output_json is None else self.output_json.encode("utf-8")
        )

    @property
    def identity(self) -> tuple[str, ...]:
        return (
            self.invocation_id,
            self.task_id,
            self.snapshot_digest,
            self.binding_digest,
            self.input_digest,
        )


def fold_native_script(events: tuple[NativeScriptEvent, ...]) -> NativeScriptEvent | None:
    last: NativeScriptEvent | None = None
    for event in events:
        if last is None:
            if event.phase != "started" or event.execution_attempt != 1:
                raise ValueError("script journal is missing its first intent")
        elif event.identity != last.identity or last.phase == "completed":
            raise ValueError("script journal changed identity or terminal result")
        elif event.phase == "completed":
            if (event.owner_fence, event.execution_attempt) != (
                last.owner_fence,
                last.execution_attempt,
            ):
                raise ValueError("late script result has lost its fence")
        elif (
            event.owner_fence == last.owner_fence
            or event.execution_attempt != last.execution_attempt + 1
        ):
            raise ValueError("script retry requires a new fence and consecutive bounded attempt")
        last = event
    return last


def script_bytes_digest(raw: bytes) -> str:
    return "sha256:" + sha256(raw).hexdigest()
