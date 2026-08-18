from typing import cast

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.model_call_store import ModelCallStorePort


class ModelCallIndexer:
    def __init__(self, model_call_store: ModelCallStorePort) -> None:
        self._model_call_store = model_call_store

    def index_event(self, event: SessionEvent) -> ModelCallRecord | None:
        if event.event_type is not EventType.MODEL_RESPONSE_RECEIVED:
            return None
        record = ModelCallRecord(
            session_id=event.session_id,
            sequence=event.sequence,
            provider=_optional_str(event.payload, "provider"),
            model_name=(
                _optional_str(event.payload, "resolved_model")
                or _optional_str(event.payload, "model_name")
            ),
            input_tokens=_optional_int(event.payload, "input_tokens"),
            estimated_input_tokens=_optional_int(event.payload, "estimated_input_tokens"),
            input_token_limit=_optional_int(event.payload, "input_token_limit"),
            input_token_estimate_error=_optional_int(event.payload, "input_token_estimate_error"),
            output_tokens=_optional_int(event.payload, "output_tokens"),
            total_tokens=_optional_int(event.payload, "total_tokens"),
            latency_ms=_optional_int(event.payload, "latency_ms"),
            cache_hit=_cache_hit(event.payload),
            cost_usd=_optional_float(event.payload, "cost_usd"),
            assistant_message=str(event.payload["assistant_message"]),
            tool_call_count=int(event.payload["tool_call_count"]),
            created_at=event.created_at,
        )
        self._model_call_store.upsert(record)
        return record

    def index_worker_event(
        self, event: SessionEvent, *, authority: WorkerMutationAuthority
    ) -> ModelCallRecord | None:
        index = getattr(self._model_call_store, "index_worker_event", None)
        if callable(index):
            return cast(ModelCallRecord | None, index(event, authority=authority))
        return self.index_event(event)


def _optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _optional_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value


def _optional_bool(payload: dict[str, object], key: str) -> bool | None:
    value = payload.get(key)
    if not isinstance(value, bool):
        return None
    return value


def _cache_hit(payload: dict[str, object]) -> bool | None:
    explicit = _optional_bool(payload, "cache_hit")
    if explicit is not None:
        return explicit
    hit_tokens = _optional_int(payload, "prompt_cache_hit_tokens")
    return None if hit_tokens is None else hit_tokens > 0


def _optional_float(payload: dict[str, object], key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
