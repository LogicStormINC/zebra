from collections.abc import Mapping
from dataclasses import dataclass, field

from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCall


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        for field_name in ("input_tokens", "output_tokens", "total_tokens"):
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
    usage: ModelUsage = field(default_factory=ModelUsage)

    def __post_init__(self) -> None:
        for field_name in ("model_call_id", "provider", "model_name", "token_estimate_method"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if not value.strip():
                raise ValueError(f"{field_name} must not be blank when set")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative")
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
