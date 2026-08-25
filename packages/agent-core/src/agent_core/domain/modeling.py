from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCall


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "reasoning_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must not be negative")


@dataclass(frozen=True)
class ModelTextDelta:
    index: int
    content: str

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("model text delta index must not be negative")
        if not self.content:
            raise ValueError("model text delta content must not be empty")


@dataclass(frozen=True)
class ModelToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("model tool name must not be blank")
        if not self.description.strip():
            raise ValueError("model tool description must not be blank")
        if self.parameters.get("type") != "object":
            raise ValueError("model tool parameters must be an object JSON schema")
        if not isinstance(self.parameters.get("properties"), Mapping):
            raise ValueError("model tool parameters must define object properties")


class ModelRole(StrEnum):
    CLASSIFIER = "classifier"
    SUMMARIZER = "summarizer"
    ANALYST = "analyst"
    PLANNER = "planner"
    REVIEWER = "reviewer"
    EXECUTOR = "executor"


class ModelThinkingMode(StrEnum):
    AUTO = "auto"
    ENABLED = "enabled"
    DISABLED = "disabled"


class ModelReasoningEffort(StrEnum):
    LOW = "low"
    HIGH = "high"
    MAX = "max"


class ModelToolChoice(StrEnum):
    AUTO = "auto"
    NONE = "none"
    REQUIRED = "required"


@dataclass(frozen=True)
class ModelInvocationPolicy:
    role: ModelRole = ModelRole.EXECUTOR
    thinking_mode: ModelThinkingMode = ModelThinkingMode.AUTO
    reasoning_effort: ModelReasoningEffort | None = None
    tool_choice: ModelToolChoice = ModelToolChoice.AUTO
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive when set")
        if self.thinking_mode is ModelThinkingMode.DISABLED and self.reasoning_effort is not None:
            raise ValueError("reasoning_effort requires thinking to be enabled or auto")


@dataclass(frozen=True)
class ModelCallMetadata:
    model_call_id: str | None = None
    provider: str | None = None
    model_name: str | None = None
    latency_ms: int | None = None
    cache_hit: bool | None = None
    cost_usd: float | None = None
    estimated_input_tokens: int | None = None
    input_token_limit: int | None = None
    token_estimate_method: str | None = None
    profile_id: str | None = None
    profile_version_observed_at: str | None = None
    requested_model: str | None = None
    resolved_model: str | None = None
    role: str | None = None
    thinking_mode: str | None = None
    reasoning_effort: str | None = None
    tool_choice: str | None = None
    prompt_version: str | None = None
    tool_schema_bytes: int | None = None
    tool_schema_hash: str | None = None
    stable_prefix_hash: str | None = None
    finish_reason: str | None = None
    time_to_first_event_ms: int | None = None
    time_to_first_public_text_ms: int | None = None
    system_fingerprint: str | None = None
    retry_count: int = 0
    response_repair_count: int = 0
    normalized_error: str | None = None
    usage: ModelUsage = field(default_factory=ModelUsage)

    def __post_init__(self) -> None:
        for field_name in (
            "model_call_id",
            "provider",
            "model_name",
            "token_estimate_method",
            "profile_id",
            "profile_version_observed_at",
            "requested_model",
            "resolved_model",
            "role",
            "thinking_mode",
            "reasoning_effort",
            "tool_choice",
            "prompt_version",
            "tool_schema_hash",
            "stable_prefix_hash",
            "finish_reason",
            "system_fingerprint",
            "normalized_error",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            if not value.strip():
                raise ValueError(f"{field_name} must not be blank when set")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative")
        for field_name in ("time_to_first_event_ms", "time_to_first_public_text_ms"):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must not be negative")
        if self.tool_schema_bytes is not None and self.tool_schema_bytes < 0:
            raise ValueError("tool_schema_bytes must not be negative")
        if self.retry_count < 0 or self.response_repair_count < 0:
            raise ValueError("model response retry counts must not be negative")
        if self.cost_usd is not None and self.cost_usd < 0:
            raise ValueError("cost_usd must not be negative")
        for field_name in ("estimated_input_tokens", "input_token_limit"):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must not be negative")


@dataclass(frozen=True)
class ModelCompletion:
    assistant_message: SessionMessage
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    call_metadata: ModelCallMetadata = field(default_factory=ModelCallMetadata)

    def __post_init__(self) -> None:
        if self.assistant_message.role is not MessageRole.ASSISTANT:
            raise ValueError("model completion assistant_message must use assistant role")


@dataclass(frozen=True)
class ModelContextWindow:
    profile_name: str = "generic-128k"
    context_tokens: int = 128_000
    max_output_tokens: int = 8_000
    reasoning_reserve_tokens: int = 0
    compaction_reserve_tokens: int = 4_000
    protocol_reserve_tokens: int = 2_000
    auto_compact_token_limit: int | None = None
    compaction_trigger_reserve_tokens: int = 2_000

    def __post_init__(self) -> None:
        for field_name in (
            "context_tokens",
            "max_output_tokens",
            "reasoning_reserve_tokens",
            "compaction_reserve_tokens",
            "protocol_reserve_tokens",
            "compaction_trigger_reserve_tokens",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must not be negative")
        if self.input_token_limit <= 0:
            raise ValueError("model context reserves leave no room for input")
        if not self.profile_name.strip():
            raise ValueError("model context profile_name must not be blank")
        if self.auto_compact_token_limit is not None:
            if self.auto_compact_token_limit <= 0:
                raise ValueError("auto_compact_token_limit must be positive")
            if self.auto_compact_token_limit > self.input_token_limit:
                raise ValueError("auto_compact_token_limit exceeds the hard input limit")

    @property
    def input_token_limit(self) -> int:
        return self.context_tokens - (
            self.max_output_tokens
            + self.reasoning_reserve_tokens
            + self.compaction_reserve_tokens
            + self.protocol_reserve_tokens
        )

    @property
    def compact_at(self) -> int:
        configured = self.auto_compact_token_limit or self.input_token_limit
        return max(
            1,
            min(configured, self.input_token_limit - self.compaction_trigger_reserve_tokens),
        )
