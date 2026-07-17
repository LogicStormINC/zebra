from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelRequestStartedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Historical v1 events carried an empty payload; keep them replayable.
    attempt_number: int | None = Field(default=None, gt=0)
    model_call_id: str | None = None
    estimated_input_tokens: int | None = Field(default=None, ge=0)
    input_token_limit: int | None = Field(default=None, ge=0)
    model_profile: str | None = None
    token_estimate_method: str | None = None
    token_breakdown: dict[str, int] | None = None
    reserves: dict[str, int] | None = None

    @field_validator("model_call_id", "model_profile", "token_estimate_method")
    @classmethod
    def ensure_model_call_id_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("model request text fields must not be blank")
        return normalized

    @field_validator("token_breakdown", "reserves")
    @classmethod
    def ensure_token_breakdown_non_negative(
        cls, value: dict[str, int] | None
    ) -> dict[str, int] | None:
        if value is not None and any(count < 0 for count in value.values()):
            raise ValueError("token breakdown values must not be negative")
        return value


class ModelResponseDeltaPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_number: int = Field(gt=0)
    model_call_id: str
    delta_index: int = Field(ge=0)
    content_delta: str

    @field_validator("model_call_id")
    @classmethod
    def ensure_model_call_id_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model_call_id must not be blank")
        return normalized

    @field_validator("content_delta")
    @classmethod
    def ensure_content_delta_not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("content_delta must not be empty")
        return value
