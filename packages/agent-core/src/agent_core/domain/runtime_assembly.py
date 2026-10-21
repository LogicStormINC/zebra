"""Frozen, public provider approval and native Bundle execution assembly."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import BeforeValidator, Field, field_validator, model_validator

from agent_core.domain.modeling import ModelContextWindow
from agent_core.domain.runtime_bundle import RuntimeBundleEnvelope
from agent_core.domain.runtime_bundle_json import json_digest
from agent_core.domain.runtime_bundle_types import ArtifactPin, BundleValue, Identifier, Text

TEXT_OUTPUT_SCHEMA = {"format": "text", "schema_version": "cloud-agent.text-output/1"}
TEXT_OUTPUT_SCHEMA_DIGEST = json_digest(TEXT_OUTPUT_SCHEMA)


def canonical_provider_profile_digest(profile: dict[str, Any] | RuntimeProviderProfile) -> str:
    payload = (
        profile.model_dump(mode="json") if isinstance(profile, RuntimeProviderProfile) else profile
    )
    return json_digest({key: value for key, value in payload.items() if key != "pin"})


class RuntimeProviderProfile(BundleValue):
    """Approval ceiling containing an environment reference, never credentials."""

    pin: ArtifactPin
    provider: Literal["openai-compatible"]
    base_url: Annotated[Text, Field(min_length=1, max_length=2048)]
    api_key_env: Annotated[Text, Field(pattern=r"^[A-Z_][A-Z0-9_]{0,127}$")]
    models: Annotated[
        tuple[Identifier, ...],
        BeforeValidator(lambda value: tuple(value) if type(value) is list else value),
        Field(min_length=1, max_length=128),
    ]
    max_context_window_tokens: Annotated[int, Field(ge=1, le=1_048_576)]
    max_output_tokens: Annotated[int, Field(ge=1, le=1_048_576)]

    @field_validator("base_url")
    @classmethod
    def require_https(cls, value: str) -> str:
        if not value.isascii() or any(
            char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value
        ):
            raise ValueError("provider base_url must be an HTTPS URL")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "?" in value
            or "#" in value
            or "\\" in value
            or parsed.netloc.endswith(":")
            or not 0 < (443 if parsed.port is None else parsed.port) <= 65535
        ):
            raise ValueError("provider base_url must be an HTTPS URL without credentials or query")
        return value

    @model_validator(mode="after")
    def approval_digest(self) -> Self:
        if (
            self.pin.kind != "provider-profile"
            or self.pin.digest != canonical_provider_profile_digest(self)
        ):
            raise ValueError("provider profile pin digest mismatch")
        if (
            len(set(self.models)) != len(self.models)
            or self.max_output_tokens > self.max_context_window_tokens
        ):
            raise ValueError("invalid provider approval limits")
        return self


class RuntimeAssembly(BundleValue):
    bundle: RuntimeBundleEnvelope
    provider_profile: RuntimeProviderProfile

    @model_validator(mode="after")
    def require_approved_native_parameters(self) -> Self:
        model = self.bundle.manifest.domains.model.parameters
        profile = self.provider_profile
        ModelContextWindow(
            context_tokens=model.context_window_tokens,
            max_output_tokens=model.max_output_tokens,
        )
        if (
            model.provider_profile != profile.pin
            or model.model not in profile.models
            or model.context_window_tokens > profile.max_context_window_tokens
            or model.max_output_tokens > profile.max_output_tokens
        ):
            raise ValueError("Bundle model exceeds exact provider approval")
        if model.thinking != "auto":
            raise ValueError("native Bundle assembly requires thinking=auto")
        if (
            self.bundle.manifest.domains.instructions.parameters.output_schema.digest
            != TEXT_OUTPUT_SCHEMA_DIGEST
        ):
            raise ValueError("native Bundle assembly requires the canonical text output schema")
        return self

    @property
    def assembly_digest(self) -> str:
        checked = type(self).model_validate(self)
        return json_digest(checked.model_dump(mode="json"))
