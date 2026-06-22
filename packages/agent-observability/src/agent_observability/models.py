from dataclasses import dataclass

from agent_core.domain.events import EventType, SessionEvent


@dataclass(frozen=True)
class CostSummary:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if self.model_calls < 0:
            raise ValueError("model_calls must not be negative")
        if self.input_tokens < 0:
            raise ValueError("input_tokens must not be negative")
        if self.output_tokens < 0:
            raise ValueError("output_tokens must not be negative")
        if self.total_tokens < 0:
            raise ValueError("total_tokens must not be negative")
        if self.cost_usd < 0:
            raise ValueError("cost_usd must not be negative")


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
