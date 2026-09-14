import type { SessionEvent } from "../types";

export type ContextPressure = "empty" | "normal" | "warning" | "critical";

export interface ContextUsageProjection {
  cacheHitRate: number | null;
  cacheHitTokens: number;
  cacheMissTokens: number;
  limitTokens: number | null;
  modelLabel: string;
  pressure: ContextPressure;
  reasoningLabel: string;
  usedTokens: number | null;
  utilization: number | null;
}

function tokenCount(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.round(value)
    : null;
}

function textValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function runtimeModelLabel(payload: Record<string, unknown> | undefined) {
  if (!payload) return "模型由运行时配置";
  const model = textValue(payload.resolved_model) ?? textValue(payload.model_name);
  const provider = textValue(payload.provider);
  if (!model) return "模型由运行时配置";
  if (!provider || model.toLowerCase().startsWith(`${provider.toLowerCase()}/`)) return model;
  const normalizedProvider = provider.toLowerCase() === "deepseek" ? "DeepSeek" : provider;
  return `${normalizedProvider}/${model}`;
}

function reasoningLabel(payload: Record<string, unknown> | undefined) {
  const effort = textValue(payload?.reasoning_effort)?.toLowerCase();
  if (effort === "high" || effort === "xhigh" || effort === "max" || effort === "ultra") return "最高";
  if (effort === "medium") return "中等";
  if (effort === "low") return "较低";
  if (effort === "minimal" || effort === "none") return "最低";
  return "自动";
}

export function projectContextUsage(events: SessionEvent[]): ContextUsageProjection {
  const responses = events.filter((event) => event.event_type === "model_response_received");
  const latestResponse = responses[responses.length - 1]?.payload;
  const latestRequest = [...events].reverse().find((event) => event.event_type === "model_request_started")?.payload;
  const usedTokens = tokenCount(latestResponse?.input_tokens)
    ?? tokenCount(latestRequest?.estimated_input_tokens)
    ?? tokenCount(latestResponse?.estimated_input_tokens);
  const limitTokens = tokenCount(latestResponse?.input_token_limit)
    ?? tokenCount(latestRequest?.input_token_limit);
  const utilization = usedTokens !== null && limitTokens !== null && limitTokens > 0
    ? Math.min(1, usedTokens / limitTokens)
    : null;
  const cache = responses.reduce(
    (total, event) => ({
      hit: total.hit + (tokenCount(event.payload.prompt_cache_hit_tokens) ?? 0),
      miss: total.miss + (tokenCount(event.payload.prompt_cache_miss_tokens) ?? 0),
    }),
    { hit: 0, miss: 0 },
  );
  const cacheTotal = cache.hit + cache.miss;
  const pressure: ContextPressure = utilization === null
    ? "empty"
    : utilization >= 0.88 ? "critical" : utilization >= 0.7 ? "warning" : "normal";

  return {
    cacheHitRate: cacheTotal > 0 ? cache.hit / cacheTotal : null,
    cacheHitTokens: cache.hit,
    cacheMissTokens: cache.miss,
    limitTokens,
    modelLabel: runtimeModelLabel(latestResponse),
    pressure,
    reasoningLabel: reasoningLabel(latestResponse),
    usedTokens,
    utilization,
  };
}

export function formatTokenCount(value: number | null): string {
  if (value === null) return "--";
  if (value >= 100_000_000) return `${Number((value / 100_000_000).toFixed(1))}亿`;
  if (value >= 10_000) return `${Number((value / 10_000).toFixed(1))}万`;
  return value.toLocaleString("zh-CN");
}
