from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class RuntimeProvisionedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_class: Literal["trusted-local", "os-sandbox", "oci-rootless", "gvisor"]
    engine: str
    image: str | None = None
    spec_digest: str
    network_enforcement: str
    workspace_writable: bool

    @field_validator("runtime_class", "engine", "network_enforcement")
    @classmethod
    def ensure_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("runtime authority fields must not be blank")
        return normalized

    @field_validator("image")
    @classmethod
    def ensure_optional_image(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("runtime image must not be blank when provided")
        return normalized

    @field_validator("spec_digest")
    @classmethod
    def ensure_sha256_digest(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64:
            raise ValueError("runtime spec_digest must be a sha256 digest")
        try:
            int(normalized, 16)
        except ValueError as exc:
            raise ValueError("runtime spec_digest must be hexadecimal") from exc
        return normalized

    @model_validator(mode="after")
    def ensure_hard_runtime_image_is_pinned(self) -> "RuntimeProvisionedPayload":
        if self.runtime_class in {"trusted-local", "os-sandbox"}:
            if self.runtime_class == "os-sandbox" and self.image is not None:
                raise ValueError("os-sandbox runtime must not declare a container image")
            return self
        if self.image is None or "@sha256:" not in self.image:
            raise ValueError("hard runtime image must be pinned by sha256 digest")
        digest = self.image.rsplit("@sha256:", 1)[-1]
        if len(digest) != 64:
            raise ValueError("hard runtime image must be pinned by sha256 digest")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError("hard runtime image digest must be hexadecimal") from exc
        return self


class RuntimeCleanupFailedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Literal["runtime", "tool_gateway"]
    error_type: str
    attempt_number: StrictInt = Field(ge=1)

    @field_validator("error_type")
    @classmethod
    def ensure_error_type(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("runtime cleanup error_type must not be blank")
        return normalized
