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


class ModelResponseReceivedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Optional fields keep historical events replayable. extra=forbid prevents
    # private provider payloads from entering durable state.
    attempt_number: int | None = Field(default=None, gt=0)
    assistant_message: str | None = None
    tool_call_count: int | None = Field(default=None, ge=0)
    response_stage: str | None = None
    model_call_id: str | None = None
    provider: str | None = None
    model_name: str | None = None
    profile_id: str | None = None
    profile_version_observed_at: str | None = None
    requested_model: str | None = None
    resolved_model: str | None = None
    role: str | None = None
    thinking_mode: str | None = None
    reasoning_effort: str | None = None
    tool_choice: str | None = None
    prompt_version: str | None = None
    tool_schema_bytes: int | None = Field(default=None, ge=0)
    tool_schema_hash: str | None = None
    stable_prefix_hash: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    prompt_cache_hit_tokens: int | None = Field(default=None, ge=0)
    prompt_cache_miss_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    time_to_first_event_ms: int | None = Field(default=None, ge=0)
    time_to_first_public_text_ms: int | None = Field(default=None, ge=0)
    finish_reason: str | None = None
    system_fingerprint: str | None = None
    retry_count: int | None = Field(default=None, ge=0)
    normalized_error: str | None = None
    cache_hit: bool | None = None
    cost_usd: float | None = Field(default=None, ge=0)
