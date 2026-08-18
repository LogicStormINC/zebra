import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HarnessAttemptStartedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Stable attempt coordinates (Wave 5 W5-DSH-02). Fields are optional so
    # pre-Phase-1 events remain replayable; the Hosted Worker writes the
    # full coordinate set for new attempts.
    attempt_number: int | None = Field(default=None, gt=0)
    attempt_id: str | None = None
    attempt_sequence: int | None = Field(default=None, gt=0)
    started_at: str | None = None
    causal_attempt_id: str | None = None
    turn_id: str | None = None
    epoch_sequence: int | None = Field(default=None, ge=0)
    clarification_continuation: bool | None = None
    clarification_id: str | None = None

    @field_validator("attempt_id", "causal_attempt_id", "started_at")
    @classmethod
    def ensure_attempt_text_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("attempt coordinate text must not be blank")
        return stripped


class AttemptOutcomeRecordedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    attempt_sequence: int = Field(gt=0)
    outcome: str
    ended_at: str
    terminal_reason: str
    retry_scheduled: bool = False
    next_attempt_sequence: int | None = Field(default=None, gt=0)
    summary: str | None = None
    result_metadata: dict[str, object] | None = None
    turn_id: str | None = None
    epoch_sequence: int | None = Field(default=None, ge=0)

    @field_validator("attempt_id", "outcome", "ended_at", "terminal_reason")
    @classmethod
    def ensure_outcome_text_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("attempt outcome text must not be blank")
        return stripped


class AttemptContinuationStartedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    attempt_sequence: int = Field(gt=0)
    continuation_kind: str
    continuation_id: str

    @field_validator(
        "attempt_id",
        "continuation_kind",
        "continuation_id",
    )
    @classmethod
    def ensure_continuation_text_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("attempt continuation text must not be blank")
        return stripped


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
    # Private request-reconstruction coordinates (W5-DSH-01). Digests are
    # recorded at dispatch and stay out of any public projection.
    stable_task_id: str | None = None
    attempt_id: str | None = None
    turn_id: str | None = None
    step_id: str | None = None
    goal_revision: int | None = Field(default=None, ge=0)
    plan_revision: int | None = Field(default=None, ge=0)
    resource_manifest_digest: str | None = None
    messages_digest: str | None = None
    system_prompt_digest: str | None = None
    tool_schema_digest: str | None = None
    model_config_digest: str | None = None
    invocation_policy_digest: str | None = None

    @field_validator("model_call_id", "model_profile", "token_estimate_method")
    @classmethod
    def ensure_model_call_id_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("model request text fields must not be blank")
        return normalized

    @field_validator(
        "stable_task_id",
        "attempt_id",
        "turn_id",
        "step_id",
        "resource_manifest_digest",
        "messages_digest",
        "system_prompt_digest",
        "tool_schema_digest",
        "model_config_digest",
        "invocation_policy_digest",
    )
    @classmethod
    def ensure_reconstruction_text_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("reconstruction coordinate text must not be blank")
        if len(stripped) > 128:
            raise ValueError("reconstruction coordinate text is too long")
        return stripped

    @field_validator(
        "resource_manifest_digest",
        "messages_digest",
        "system_prompt_digest",
        "tool_schema_digest",
        "model_config_digest",
        "invocation_policy_digest",
    )
    @classmethod
    def ensure_reconstruction_digest_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", stripped):
            raise ValueError("reconstruction digests must use the sha256:<64 hex> envelope")
        return stripped

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
    attempt_id: str | None = None
    stable_task_id: str | None = None
    assistant_message: str | None = None
    tool_call_count: int | None = Field(default=None, ge=0)
    proposed_tool_names: tuple[str, ...] | None = None
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
    estimated_input_tokens: int | None = Field(default=None, ge=0)
    input_token_limit: int | None = Field(default=None, ge=0)
    token_estimate_method: str | None = None
    input_token_estimate_error: int | None = None
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
    response_repair_count: int | None = Field(default=None, ge=0)
    normalized_error: str | None = None
    cache_hit: bool | None = None
    cost_usd: float | None = Field(default=None, ge=0)
    output_contract: dict[str, object] | None = None

    @field_validator("output_contract")
    @classmethod
    def ensure_output_contract_generic_envelope(
        cls, value: dict[str, object] | None
    ) -> dict[str, object] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("output_contract must be an object")
        contract_id = value.get("contract_id")
        contract_version = value.get("contract_version")
        payload = value.get("structured_payload")
        digest = value.get("payload_digest")
        refs = value.get("source_refs")
        if not isinstance(contract_id, str) or not contract_id.strip():
            raise ValueError("output_contract.contract_id must be a non-blank string")
        if not isinstance(contract_version, str) or not contract_version.strip():
            raise ValueError("output_contract.contract_version must be a non-blank string")
        if not isinstance(payload, dict):
            raise ValueError("output_contract.structured_payload is required and must be an object")
        if digest is not None and (
            not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        ):
            raise ValueError(
                "output_contract.payload_digest, when provided, must be sha256:<64 hex>"
            )
        if (
            not isinstance(refs, list)
            or not refs
            or not all(isinstance(item, str) and item.strip() for item in refs)
        ):
            raise ValueError(
                "output_contract.source_refs is required and must be a non-empty text array"
            )
        return value

    @field_validator("attempt_id", "stable_task_id")
    @classmethod
    def ensure_response_identity_text_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("response identity text must not be blank")
        return stripped
