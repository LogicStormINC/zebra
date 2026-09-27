from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCall

CONTEXT_TOKEN_CATEGORIES = (
    "messages",
    "system_tools",
    "skills",
    "system_prompt",
    "mcp_tools",
    "other",
)


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


class ModelToolOrigin(StrEnum):
    SYSTEM = "system"
    HOST = "host"
    CLIENT = "client"
    MANAGEMENT = "management"
    MCP = "mcp"


@dataclass(frozen=True)
class ModelToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, object]
    origin: ModelToolOrigin = ModelToolOrigin.SYSTEM
    source_id: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("model tool name must not be blank")
        if not self.description.strip():
            raise ValueError("model tool description must not be blank")
        if self.parameters.get("type") != "object":
            raise ValueError("model tool parameters must be an object JSON schema")
        if not isinstance(self.parameters.get("properties"), Mapping):
            raise ValueError("model tool parameters must define object properties")
        if self.source_id is not None and not self.source_id.strip():
            raise ValueError("model tool source_id must not be blank when set")


@dataclass(frozen=True)
class ModelTokenBreakdown:
    categories: Mapping[str, int]
    basis: str
    estimate_method: str
    raw_estimated_total: int
    provider_input_tokens: int | None = None
    estimate_error: int | None = None
    schema_version: int = 2

    def __post_init__(self) -> None:
        if self.schema_version != 2:
            raise ValueError("model token breakdown schema_version must be 2")
        if set(self.categories) != set(CONTEXT_TOKEN_CATEGORIES):
            raise ValueError("model token breakdown must contain every context category")
        if any(value < 0 for value in self.categories.values()):
            raise ValueError("model token breakdown categories must not be negative")
        if not self.basis.strip() or not self.estimate_method.strip():
            raise ValueError("model token breakdown basis and estimate_method must not be blank")
        if self.raw_estimated_total < 0:
            raise ValueError("raw_estimated_total must not be negative")
        if self.provider_input_tokens is not None and self.provider_input_tokens < 0:
            raise ValueError("provider_input_tokens must not be negative")

    @property
    def total_tokens(self) -> int:
        return sum(self.categories.values())

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "basis": self.basis,
            "estimate_method": self.estimate_method,
            "total_tokens": self.total_tokens,
            "categories": dict(self.categories),
            "raw_estimated_total": self.raw_estimated_total,
        }
        if self.provider_input_tokens is not None:
            payload["provider_input_tokens"] = self.provider_input_tokens
        if self.estimate_error is not None:
            payload["estimate_error"] = self.estimate_error
        return payload


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
    profile_id: str | None = None

    def __post_init__(self) -> None:
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive when set")
        if self.thinking_mode is ModelThinkingMode.DISABLED and self.reasoning_effort is not None:
            raise ValueError("reasoning_effort requires thinking to be enabled or auto")
        if self.profile_id is not None and not self.profile_id.strip():
            raise ValueError("profile_id must not be blank when set")


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
    token_breakdown: Mapping[str, int] | None = None
    token_breakdown_v2: ModelTokenBreakdown | None = None
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
    request_hash: str | None = None
    message_count: int | None = None
    message_prefix_hashes: tuple[str, ...] = ()
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
            "request_hash",
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
        if self.message_count is not None and self.message_count < 0:
            raise ValueError("message_count must not be negative")
        if len(self.message_prefix_hashes) > 256:
            raise ValueError("message_prefix_hashes must be bounded")
        if any(not value.strip() for value in self.message_prefix_hashes):
            raise ValueError("message_prefix_hashes must not contain blanks")
        if self.retry_count < 0 or self.response_repair_count < 0:
            raise ValueError("model response retry counts must not be negative")
        if self.cost_usd is not None and self.cost_usd < 0:
            raise ValueError("cost_usd must not be negative")
        for field_name in ("estimated_input_tokens", "input_token_limit"):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must not be negative")
        if self.token_breakdown is not None and any(
            not key.strip() or isinstance(value, bool) or value < 0
            for key, value in self.token_breakdown.items()
        ):
            raise ValueError("token_breakdown must contain named non-negative counts")


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
