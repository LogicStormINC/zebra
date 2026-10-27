"""Producer-owned immutable values for the first, effect-free script ABI."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.runtime_bundle_json import canonical_json_bytes, load_bundle_json
from agent_core.domain.runtime_bundle_types import Digest, Identifier, Version

SCRIPT_ABI = "cloud-agent.native-script/1"
MAX_SCRIPT_BYTES = 16_384
MAX_SCRIPT_INPUT_BYTES = 16_384
MAX_SCRIPT_OUTPUT_BYTES = 32_768
ScalarType = Literal["string", "integer", "boolean"]
FieldName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class NativeScriptError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ScriptValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, revalidate_instances="always"
    )


class ScriptField(ScriptValue):
    name: FieldName
    type: ScalarType


class ScriptShape(ScriptValue):
    # ponytail: closed scalar records avoid a second JSON Schema engine. Nested,
    # optional, array and floating fields require a separately versioned ABI.
    fields: tuple[ScriptField, ...] = Field(max_length=32)

    @field_validator("fields", mode="before")
    @classmethod
    def json_array(cls, value: object) -> object:
        return tuple(value) if type(value) is list else value

    @model_validator(mode="after")
    def unique_names(self) -> Self:
        if len({field.name for field in self.fields}) != len(self.fields):
            raise ValueError("duplicate script field")
        return self

    def validate_record(self, value: object) -> None:
        if type(value) is not dict or set(value) != {field.name for field in self.fields}:
            raise NativeScriptError("record_fields_mismatch")
        types = {"string": str, "integer": int, "boolean": bool}
        for field in self.fields:
            item = value[field.name]
            if type(item) is not types[field.type]:
                raise NativeScriptError("record_type_mismatch")
            if type(item) is str and len(item.encode("utf-8")) > 4096:
                raise NativeScriptError("record_string_too_large")
        canonical_json_bytes(value)


class NativeScriptManifest(ScriptValue):
    abi: Literal["cloud-agent.native-script/1"]
    name: Identifier
    version: Version
    kind: Literal["tool", "context", "verifier"]
    source_digest: Digest
    python: Literal["3.12"]
    dependencies: Literal["stdlib-only"]
    entrypoint: Literal["execute"]
    effects: Literal["none"]
    input: ScriptShape
    output: ScriptShape
    timeout_seconds: Annotated[int, Field(ge=1, le=30)]
    max_output_bytes: Annotated[int, Field(ge=256, le=MAX_SCRIPT_OUTPUT_BYTES)]

    @model_validator(mode="after")
    def entry_output(self) -> Self:
        fields = {field.name: field.type for field in self.output.fields}
        if self.kind == "context" and fields.get("text") != "string":
            raise ValueError("context requires a text output")
        if self.kind == "verifier" and fields.get("passed") != "boolean":
            raise ValueError("verifier requires a passed output")
        return self

    @property
    def digest(self) -> str:
        return "sha256:" + sha256(canonical_json_bytes(self.model_dump(mode="json"))).hexdigest()


@dataclass(frozen=True)
class NativeScript:
    manifest: NativeScriptManifest
    source: bytes

    def __post_init__(self) -> None:
        NativeScriptManifest.model_validate(self.manifest)
        if type(self.source) is not bytes or not 0 < len(self.source) <= MAX_SCRIPT_BYTES:
            raise NativeScriptError("invalid_source_size")
        if "sha256:" + sha256(self.source).hexdigest() != self.manifest.source_digest:
            raise NativeScriptError("source_digest_mismatch")
        try:
            compile(self.source.decode("utf-8"), "<native-script>", "exec")
        except (ValueError, SyntaxError, UnicodeError):
            raise NativeScriptError("invalid_python_source") from None


def parse_native_script(manifest: bytes, source: bytes) -> NativeScript:
    try:
        if type(manifest) is not bytes or len(manifest) > MAX_SCRIPT_BYTES:
            raise ValueError("manifest size")
        value = load_bundle_json(manifest)
        return NativeScript(NativeScriptManifest.model_validate(value), source)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise NativeScriptError("invalid_script_package") from None
