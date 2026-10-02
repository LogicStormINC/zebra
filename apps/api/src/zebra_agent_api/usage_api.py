"""Principal-scoped, provider-reported Cloud usage evidence for Host UIs."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from agent_core.domain.host_authority import HostContextEnvelope

from zebra_agent_api.responses import ApiResponse

if TYPE_CHECKING:
    from zebra_agent_api.routes import RouteRequest


class UsageEvidenceReader(Protocol):
    @property
    def deployment_namespace(self) -> str: ...

    def read(
        self, context: HostContextEnvelope, *, start: datetime, end: datetime
    ) -> list[dict[str, Any]]: ...


def handle_usage_route(
    reader: UsageEvidenceReader | None, request: RouteRequest
) -> ApiResponse | None:
    if request.path != "/usage" or request.method.upper() != "GET":
        return None
    context = request.host_context
    if context is None:
        return ApiResponse(401, {"status": "unauthorized", "reason": "host_authority_required"})
    if "event.read" not in context.scopes:
        return ApiResponse(403, {"status": "forbidden", "reason": "event_read_scope_required"})
    if sum(ref.resource_type == "principal" for ref in context.resource_refs) != 1:
        return ApiResponse(403, {"status": "forbidden", "reason": "principal_scope_required"})
    if reader is None:
        return ApiResponse(503, {"status": "unavailable", "reason": "cloud_usage_unavailable"})
    raw_days = (request.query or {}).get("days", "7")
    if raw_days not in {"7", "30"}:
        return ApiResponse(400, {"status": "invalid_request", "reason": "days must be 7 or 30"})
    days = int(raw_days)
    today = datetime.now(UTC).date()
    start = datetime.combine(today - timedelta(days=days - 1), time.min, tzinfo=UTC)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=UTC)
    rows = reader.read(context, start=start, end=end)
    if len(rows) > 100_000:
        return ApiResponse(503, {"status": "unavailable", "reason": "usage_window_too_large"})
    return ApiResponse(200, summarize_usage(rows, days=days, start=start))


def summarize_usage(rows: list[dict[str, Any]], *, days: int, start: datetime) -> dict[str, object]:
    totals = _empty_counts()
    daily = {
        (start + timedelta(days=offset)).date().isoformat(): _empty_counts()
        for offset in range(days)
    }
    tasks: dict[str, dict[str, Any]] = {}
    models: dict[str, dict[str, int]] = {}
    daily_models: dict[tuple[str, str], dict[str, Any]] = {}
    tools: dict[str, int] = {}
    for row in rows:
        stamp = row.get("created_at")
        if not isinstance(stamp, datetime) or stamp.tzinfo is None:
            continue
        day = stamp.astimezone(UTC).date().isoformat()
        if day not in daily:
            continue
        task_id = str(row.get("task_id") or "")
        if not task_id:
            continue
        task = tasks.setdefault(
            task_id,
            {
                "task_id": task_id,
                "title": str(row.get("title") or "未命名会话")[:120],
                **_empty_counts(),
            },
        )
        buckets = (totals, daily[day], task)
        kind = str(row.get("event_type") or "")
        if kind == "user_message_received":
            _increment(buckets, "messages")
        elif kind in {"tool_execution_completed", "tool_execution_failed"}:
            _increment(buckets, "tool_calls")
            name = str(row.get("tool_name") or "其他")[:80]
            tools[name] = tools.get(name, 0) + 1
        elif kind == "model_response_received":
            _increment(buckets, "model_calls")
            input_count = _count(row.get("input_tokens"))
            output_count = _count(row.get("output_tokens"))
            provider_total = _count(row.get("total_tokens"))
            known_total = (
                provider_total
                if provider_total is not None
                else input_count + output_count
                if input_count is not None and output_count is not None
                else None
            )
            if known_total is None:
                _increment(buckets, "unmetered_calls")
            for field, value in (
                ("input_tokens", input_count),
                ("output_tokens", output_count),
                ("total_tokens", known_total),
                ("reasoning_tokens", _count(row.get("reasoning_tokens"))),
                ("cache_hit_tokens", _count(row.get("cache_hit_tokens"))),
                ("cache_miss_tokens", _count(row.get("cache_miss_tokens"))),
            ):
                if value is not None:
                    _increment(buckets, field, value)
            model = str(row.get("resolved_model") or row.get("model_name") or "未知模型")[:80]
            by_model = models.setdefault(model, _empty_counts())
            by_day_model = daily_models.setdefault(
                (day, model),
                {
                    "date": day,
                    "model": model,
                    **_empty_counts(),
                },
            )
            _increment((by_model, by_day_model), "model_calls")
            if known_total is not None:
                _increment((by_model, by_day_model), "total_tokens", known_total)
    return {
        "schema_version": 1,
        "source": "committed_cloud_events",
        "period": {
            "days": days,
            "start": start.date().isoformat(),
            "end": (start + timedelta(days=days - 1)).date().isoformat(),
            "timezone": "UTC",
        },
        "totals": totals,
        "daily": [{"date": day, **counts} for day, counts in daily.items()],
        "daily_models": sorted(
            daily_models.values(), key=lambda item: (item["date"], item["model"])
        ),
        "models": [
            {"model": model, **counts}
            for model, counts in sorted(
                models.items(), key=lambda item: item[1]["total_tokens"], reverse=True
            )
        ],
        "tools": [
            {"name": name, "calls": count}
            for name, count in sorted(tools.items(), key=lambda item: item[1], reverse=True)
        ],
        "tasks": sorted(tasks.values(), key=lambda item: item["total_tokens"], reverse=True),
    }


def _empty_counts() -> dict[str, int]:
    return {
        key: 0
        for key in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "reasoning_tokens",
            "cache_hit_tokens",
            "cache_miss_tokens",
            "model_calls",
            "unmetered_calls",
            "tool_calls",
            "messages",
        )
    }


def _increment(buckets: tuple[dict[str, Any], ...], key: str, value: int = 1) -> None:
    for bucket in buckets:
        bucket[key] = int(bucket[key]) + value


def _count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    return None
