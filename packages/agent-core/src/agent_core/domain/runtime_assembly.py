"""Frozen, public provider approval and native Bundle execution assembly."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import BeforeValidator, Field, field_validator, model_serializer, model_validator

from agent_core.domain.modeling import ModelContextWindow
from agent_core.domain.runtime_bundle import RuntimeBundleEnvelope
from agent_core.domain.runtime_bundle_json import json_digest
from agent_core.domain.runtime_bundle_types import (
    ArtifactPin,
    BundleValue,
    ConfigurableBudgetDomain,
    Identifier,
    Text,
)

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
    display_name: Annotated[Text, Field(min_length=1, max_length=256)] | None = None
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

    @model_serializer(mode="wrap")
    def serialize_profile(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if self.display_name is None:
            data.pop("display_name", None)
        return data

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


class BudgetProfile(BundleValue):
    """Approval ceiling for the root Task budget; never a reservation itself."""

    pin: ArtifactPin
    max_model_tokens: Annotated[int, Field(ge=0)]
    max_tool_calls: Annotated[int, Field(ge=0)]
    max_runtime_seconds: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def approval_digest(self) -> Self:
        if self.pin.kind != "budget-profile" or self.pin.digest != canonical_budget_profile_digest(
            self
        ):
            raise ValueError("budget profile pin digest mismatch")
        return self


def canonical_budget_profile_digest(profile: BudgetProfile | dict[str, Any]) -> str:
    payload = profile.model_dump(mode="json") if isinstance(profile, BudgetProfile) else profile
    return json_digest({key: value for key, value in payload.items() if key != "pin"})


class RuntimeAssembly(BundleValue):
    bundle: RuntimeBundleEnvelope
    provider_profile: RuntimeProviderProfile
    budget_profile: BudgetProfile
    selectable_profiles: Annotated[
        tuple[RuntimeProviderProfile, ...],
        BeforeValidator(lambda value: tuple(value) if type(value) is list else value),
        Field(max_length=16),
    ] = Field(default=(), exclude_if=lambda value: not value)

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
        if len(model.selectable_models) != len(self.selectable_profiles):
            raise ValueError("selectable model approval set differs from Bundle")
        for choice, approval in zip(model.selectable_models, self.selectable_profiles, strict=True):
            if (
                choice.provider_profile != approval.pin
                or choice.model not in approval.models
                or model.context_window_tokens > approval.max_context_window_tokens
                or model.max_output_tokens > approval.max_output_tokens
            ):
                raise ValueError("selectable model exceeds exact provider approval")
        if model.thinking != "auto":
            raise ValueError("native Bundle assembly requires thinking=auto")
        budget = self.bundle.manifest.domains.budget
        if isinstance(budget, ConfigurableBudgetDomain):
            parameters = budget.parameters
            budget_ceiling = self.budget_profile
            if (
                parameters.budget_profile != budget_ceiling.pin
                or parameters.model_tokens > budget_ceiling.max_model_tokens
                or parameters.tool_calls > budget_ceiling.max_tool_calls
                or parameters.runtime_seconds > budget_ceiling.max_runtime_seconds
            ):
                raise ValueError("Bundle budget exceeds exact budget approval")
        # pinned budget 保持合法（无预算批准被消费）；合同切换后在装配层收紧。
        if (
            self.bundle.manifest.domains.instructions.parameters.output_schema.digest
            != TEXT_OUTPUT_SCHEMA_DIGEST
        ):
            raise ValueError("native Bundle assembly requires the canonical text output schema")
        return self

    def resolve_session_model(
        self, *, requested_id: str | None, remembered_id: str | None
    ) -> tuple[str, RuntimeProviderProfile]:
        """Resolve a send against this release's approved models."""
        model = self.bundle.manifest.domains.model.parameters
        selected_id = requested_id if requested_id is not None else remembered_id
        if selected_id is None or selected_id == self.provider_profile.pin.id:
            return model.model, self.provider_profile
        for choice, profile in zip(model.selectable_models, self.selectable_profiles, strict=True):
            if profile.pin.id == selected_id:
                return choice.model, profile
        if requested_id is not None:
            raise ValueError("requested model is not selectable in this release")
        return model.model, self.provider_profile

    @property
    def assembly_digest(self) -> str:
        checked = type(self).model_validate(self)
        return json_digest(checked.model_dump(mode="json"))
