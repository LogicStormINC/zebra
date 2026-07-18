from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from agent_observability.models import ProviderModelCallTrace, TraceRecord


@dataclass(frozen=True)
class ModelProfileSummary:
    profile_id: str
    call_count: int
    successful_call_count: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    cost_usd: float
    average_latency_ms: float | None
    finish_reasons: tuple[tuple[str, int], ...]


def summarize_model_profiles(
    traces: tuple[TraceRecord, ...],
) -> tuple[ModelProfileSummary, ...]:
    grouped: dict[str, list[ProviderModelCallTrace]] = defaultdict(list)
    for trace in traces:
        for call in trace.model_calls:
            grouped[call.profile_id or "unprofiled"].append(call)
    return tuple(_summarize(profile_id, grouped[profile_id]) for profile_id in sorted(grouped))


def _summarize(
    profile_id: str,
    calls: list[ProviderModelCallTrace],
) -> ModelProfileSummary:
    latencies = [call.latency_ms for call in calls if call.latency_ms is not None]
    finish_reasons = Counter(call.finish_reason or "unknown" for call in calls)
    return ModelProfileSummary(
        profile_id=profile_id,
        call_count=len(calls),
        successful_call_count=sum(
            call.normalized_error is None and call.finish_reason in {None, "stop", "tool_calls"}
            for call in calls
        ),
        input_tokens=sum(call.input_tokens or 0 for call in calls),
        output_tokens=sum(call.output_tokens or 0 for call in calls),
        reasoning_tokens=sum(call.reasoning_tokens or 0 for call in calls),
        prompt_cache_hit_tokens=sum(call.prompt_cache_hit_tokens or 0 for call in calls),
        prompt_cache_miss_tokens=sum(call.prompt_cache_miss_tokens or 0 for call in calls),
        cost_usd=sum(call.cost_usd or 0.0 for call in calls),
        average_latency_ms=(sum(latencies) / len(latencies) if latencies else None),
        finish_reasons=tuple(sorted(finish_reasons.items())),
    )
