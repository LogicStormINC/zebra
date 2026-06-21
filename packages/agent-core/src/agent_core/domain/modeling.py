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
class ModelCallMetadata:
    provider: str | None = None
    model_name: str | None = None
    latency_ms: int | None = None
    cache_hit: bool | None = None
    cost_usd: float | None = None
    usage: ModelUsage = field(default_factory=ModelUsage)

    def __post_init__(self) -> None:
        for field_name in ("provider", "model_name"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if not value.strip():
                raise ValueError(f"{field_name} must not be blank when set")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative")
        if self.cost_usd is not None and self.cost_usd < 0:
            raise ValueError("cost_usd must not be negative")


@dataclass(frozen=True)
class ModelCompletion:
    assistant_message: SessionMessage
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    call_metadata: ModelCallMetadata = field(default_factory=ModelCallMetadata)

    def __post_init__(self) -> None:
        if self.assistant_message.role is not MessageRole.ASSISTANT:
            raise ValueError("model completion assistant_message must use assistant role")
