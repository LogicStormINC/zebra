"""Strict immutable values for the validation-only Runtime Bundle contract."""

from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _unicode(value: str) -> str:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError("invalid Unicode")
    return value


Text = Annotated[str, AfterValidator(_unicode)]
Digest = Annotated[Text, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Identifier = Annotated[
    Text, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+(?:[./][A-Za-z0-9_-]+)*$")
]
Version = Annotated[
    Text,
    Field(
        max_length=64,
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$",
    ),
]
AssetKind = Literal[
    "image", "baseline-config", "component", "provider-profile", "output-schema", "build-evidence"
]


class BundleValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, revalidate_instances="always"
    )


class ArtifactPin(BundleValue):
    kind: AssetKind
    id: Identifier
    version: Version
    digest: Digest


class EngineBinding(BundleValue):
    kind: Literal["cloud-agent"]
    image: ArtifactPin
    bundle_abi: Literal["cloud-agent.bundle/1"]
    script_abi: Literal["unsupported"]

    @model_validator(mode="after")
    def image_kind(self) -> Self:
        if self.image.kind != "image":
            raise ValueError("image pin required")
        return self


def _issuer(value: str) -> str:
    if not value.isascii() or any(
        char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value
    ):
        raise ValueError("invalid authority issuer")
    parsed = urlsplit(value)
    port = 443 if parsed.port is None else parsed.port
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "?" in value
        or "#" in value
        or "\\" in value
        or parsed.netloc.endswith(":")
        or not 0 < port <= 65535
    ):
        raise ValueError("HTTPS authority issuer required")
    return value


class BundleScope(BundleValue):
    authority_issuer: Annotated[Text, Field(min_length=1, max_length=2048), AfterValidator(_issuer)]
    namespace_id: Identifier
    product_id: Identifier
    environment: Identifier
    target_id: Identifier
    deployment_id: Identifier


class ModelParameters(BundleValue):
    provider_profile: ArtifactPin
    model: Identifier
    context_window_tokens: Annotated[int, Field(ge=1, le=1_048_576)]
    max_output_tokens: Annotated[int, Field(ge=1, le=1_048_576)]
    max_retries: Annotated[int, Field(ge=0, le=3)]
    temperature_milli: Annotated[int, Field(ge=0, le=2000)]
    thinking: Literal["auto", "enabled", "disabled"]

    @model_validator(mode="after")
    def valid_model(self) -> Self:
        if self.provider_profile.kind != "provider-profile":
            raise ValueError("provider profile pin required")
        if self.max_output_tokens > self.context_window_tokens:
            raise ValueError("output exceeds context window")
        return self


class InstructionsParameters(BundleValue):
    system_text: Annotated[Text, Field(max_length=32_768)]
    business_text: Annotated[Text, Field(max_length=32_768)]
    locale: Annotated[Text, Field(max_length=64, pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")]
    output_schema: ArtifactPin

    @model_validator(mode="after")
    def output_kind(self) -> Self:
        if self.output_schema.kind != "output-schema":
            raise ValueError("output schema pin required")
        return self


class EmptyParameters(BundleValue):
    """Pinned domains cannot smuggle configuration through a mutable mapping."""


class PinnedDomain(BundleValue):
    component: ArtifactPin
    mode: Literal["pinned"]
    reason: Literal["requires-runtime-assembly"]
    parameters: EmptyParameters


class ModelDomain(BundleValue):
    component: ArtifactPin
    mode: Literal["configurable"]
    parameters: ModelParameters


class InstructionsDomain(BundleValue):
    component: ArtifactPin
    mode: Literal["configurable"]
    parameters: InstructionsParameters


class RuntimeDomains(BundleValue):
    engine: PinnedDomain
    execution: PinnedDomain
    model: ModelDomain
    instructions: InstructionsDomain
    context: PinnedDomain
    memory: PinnedDomain
    content: PinnedDomain
    native: PinnedDomain
    addons: PinnedDomain
    tools: PinnedDomain
    lifecycle: PinnedDomain
    policy: PinnedDomain
    sandbox: PinnedDomain
    storage: PinnedDomain
    transport: PinnedDomain
    frontend: PinnedDomain
    triggers: PinnedDomain
    budget: PinnedDomain
    verification: PinnedDomain
    operations: PinnedDomain
