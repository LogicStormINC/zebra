from agent_observability import (
    CostSummary,
    ProviderModelCallTrace,
    TraceRecord,
    summarize_model_profiles,
)


def test_summarize_model_profiles_supports_offline_flash_pro_comparison() -> None:
    trace = TraceRecord(
        session_id="session-1",
        event_count=3,
        tool_result_count=1,
        cost=CostSummary(),
        audit=(),
        model_calls=(
            _call(
                "deepseek-v4-flash-executor-v1",
                latency_ms=100,
                input_tokens=100,
                output_tokens=20,
                reasoning_tokens=0,
                cache_hit_tokens=80,
                cache_miss_tokens=20,
                cost_usd=0.01,
            ),
            _call(
                "deepseek-v4-pro-reviewer-v1",
                latency_ms=300,
                input_tokens=120,
                output_tokens=30,
                reasoning_tokens=10,
                cache_hit_tokens=90,
                cache_miss_tokens=30,
                cost_usd=0.03,
            ),
        ),
    )

    flash, pro = summarize_model_profiles((trace,))

    assert flash.profile_id == "deepseek-v4-flash-executor-v1"
    assert flash.successful_call_count == 1
    assert flash.average_latency_ms == 100
    assert flash.prompt_cache_hit_tokens == 80
    assert pro.profile_id == "deepseek-v4-pro-reviewer-v1"
    assert pro.reasoning_tokens == 10
    assert pro.cost_usd == 0.03
    assert pro.finish_reasons == (("stop", 1),)


def _call(
    profile_id: str,
    *,
    latency_ms: int,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
    cache_hit_tokens: int,
    cache_miss_tokens: int,
    cost_usd: float,
) -> ProviderModelCallTrace:
    return ProviderModelCallTrace(
        sequence=1,
        profile_id=profile_id,
        finish_reason="stop",
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        prompt_cache_hit_tokens=cache_hit_tokens,
        prompt_cache_miss_tokens=cache_miss_tokens,
        cost_usd=cost_usd,
    )
