from dataclasses import dataclass

from agent_core.domain.events import EventType, SessionEvent


@dataclass(frozen=True)
class CostSummary:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    reasoning_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0

    def __post_init__(self) -> None:
        if self.model_calls < 0:
            raise ValueError("model_calls must not be negative")
        if self.input_tokens < 0:
            raise ValueError("input_tokens must not be negative")
        if self.output_tokens < 0:
            raise ValueError("output_tokens must not be negative")
        if self.total_tokens < 0:
            raise ValueError("total_tokens must not be negative")
        for field_name in (
            "reasoning_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must not be negative")
        if self.cost_usd < 0:
            raise ValueError("cost_usd must not be negative")


@dataclass(frozen=True)
class ProviderModelCallTrace:
    sequence: int
    profile_id: str | None = None
    profile_version_observed_at: str | None = None
    provider: str | None = None
    requested_model: str | None = None
    resolved_model: str | None = None
    role: str | None = None
    thinking_mode: str | None = None
    reasoning_effort: str | None = None
    tool_choice: str | None = None
    finish_reason: str | None = None
    time_to_first_event_ms: int | None = None
    time_to_first_public_text_ms: int | None = None
    latency_ms: int | None = None
    retry_count: int = 0
    normalized_error: str | None = None
    system_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0 or self.retry_count < 0:
            raise ValueError("model trace counts must not be negative")
        for field_name in (
            "time_to_first_event_ms",
            "time_to_first_public_text_ms",
            "latency_ms",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must not be negative")


@dataclass(frozen=True)
class AuditRecord:
    sequence: int
    event_type: EventType
    actor: str
    summary: str

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("audit sequence must not be negative")
        if not self.actor.strip():
            raise ValueError("audit actor must not be blank")
        if not self.summary.strip():
            raise ValueError("audit summary must not be blank")


@dataclass(frozen=True)
class TraceRecord:
    session_id: str
    event_count: int
    tool_result_count: int
    cost: CostSummary
    audit: tuple[AuditRecord, ...]
    model_calls: tuple[ProviderModelCallTrace, ...] = ()

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("trace session_id must not be blank")
        if self.event_count < 0:
            raise ValueError("trace event_count must not be negative")
        if self.tool_result_count < 0:
            raise ValueError("trace tool_result_count must not be negative")
        if len(self.audit) > self.event_count:
            raise ValueError("trace audit cannot exceed event count")


def build_trace_record(events: tuple[SessionEvent, ...]) -> TraceRecord:
    if not events:
        raise ValueError("trace requires at least one event")
    session_id = str(events[0].session_id)
    if any(str(event.session_id) != session_id for event in events):
        raise ValueError("trace events must belong to one session")
    return TraceRecord(
        session_id=session_id,
        event_count=len(events),
        tool_result_count=_tool_result_count(events),
        cost=_cost_summary(events),
        audit=tuple(_audit_record(event) for event in events),
        model_calls=tuple(
            _model_call_trace(event)
            for event in events
            if event.event_type is EventType.MODEL_RESPONSE_RECEIVED
        ),
    )


def _tool_result_count(events: tuple[SessionEvent, ...]) -> int:
    result_events = {
        EventType.TOOL_EXECUTION_COMPLETED,
        EventType.TOOL_EXECUTION_FAILED,
    }
    return sum(1 for event in events if event.event_type in result_events)


def _cost_summary(events: tuple[SessionEvent, ...]) -> CostSummary:
    model_events = [
        event for event in events if event.event_type is EventType.MODEL_RESPONSE_RECEIVED
    ]
    return CostSummary(
        model_calls=len(model_events),
        input_tokens=sum(_int_payload(event, "input_tokens") for event in model_events),
        output_tokens=sum(_int_payload(event, "output_tokens") for event in model_events),
        total_tokens=sum(_int_payload(event, "total_tokens") for event in model_events),
        cost_usd=sum(_float_payload(event, "cost_usd") for event in model_events),
        reasoning_tokens=sum(_int_payload(event, "reasoning_tokens") for event in model_events),
        prompt_cache_hit_tokens=sum(
            _int_payload(event, "prompt_cache_hit_tokens") for event in model_events
        ),
        prompt_cache_miss_tokens=sum(
            _int_payload(event, "prompt_cache_miss_tokens") for event in model_events
        ),
    )


def _model_call_trace(event: SessionEvent) -> ProviderModelCallTrace:
    return ProviderModelCallTrace(
        sequence=event.sequence,
        profile_id=_str_payload(event, "profile_id"),
        profile_version_observed_at=_str_payload(event, "profile_version_observed_at"),
        provider=_str_payload(event, "provider"),
        requested_model=_str_payload(event, "requested_model"),
        resolved_model=(_str_payload(event, "resolved_model") or _str_payload(event, "model_name")),
        role=_str_payload(event, "role"),
        thinking_mode=_str_payload(event, "thinking_mode"),
        reasoning_effort=_str_payload(event, "reasoning_effort"),
        tool_choice=_str_payload(event, "tool_choice"),
        finish_reason=_str_payload(event, "finish_reason"),
        time_to_first_event_ms=_optional_int_payload(event, "time_to_first_event_ms"),
        time_to_first_public_text_ms=_optional_int_payload(event, "time_to_first_public_text_ms"),
        latency_ms=_optional_int_payload(event, "latency_ms"),
        retry_count=_int_payload(event, "retry_count"),
        normalized_error=_str_payload(event, "normalized_error"),
        system_fingerprint=_str_payload(event, "system_fingerprint"),
    )


def _audit_record(event: SessionEvent) -> AuditRecord:
    return AuditRecord(
        sequence=event.sequence,
        event_type=event.event_type,
        actor=event.actor.value,
        summary=f"{event.actor.value}:{event.event_type.value}",
    )


def _int_payload(event: SessionEvent, key: str) -> int:
    value = event.payload.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return int(value)


def _float_payload(event: SessionEvent, key: str) -> float:
    value = event.payload.get(key, 0.0)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


def _optional_int_payload(event: SessionEvent, key: str) -> int | None:
    value = event.payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _str_payload(event: SessionEvent, key: str) -> str | None:
    value = event.payload.get(key)
    if not isinstance(value, str):
        return None
    return value.strip() or None
