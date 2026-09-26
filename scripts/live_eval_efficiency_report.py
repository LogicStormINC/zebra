from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_observability import CacheBoundary, build_trace_record
from agent_storage import SQLiteEventStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Report measured real-model cache boundaries")
    parser.add_argument("--attempts", required=True, type=Path)
    args = parser.parse_args()
    segments: dict[str, list[dict[str, object]]] = defaultdict(list)
    attempts = [json.loads(line) for line in args.attempts.read_text().splitlines() if line]
    for attempt in attempts:
        capture = attempt["capture"]
        metrics = list(capture.get("model_metrics") or ())
        if not metrics or any(not item.get("cache_boundary") for item in metrics):
            metrics = _load_model_metrics(capture)
        for metric in metrics:
            boundary = str(metric.get("cache_boundary") or CacheBoundary.UNKNOWN.value)
            segments[boundary].append(metric)
    measured = set(segments)
    expected = tuple(
        boundary.value for boundary in CacheBoundary if boundary is not CacheBoundary.UNKNOWN
    )
    report = {
        "schema": "zebra.live-eval-efficiency.v1",
        "attempt_count": len(attempts),
        "segments": {name: _summarize(values) for name, values in sorted(segments.items())},
        "unmeasured_segments": [name for name in expected if name not in measured],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _summarize(values: list[dict[str, object]]) -> dict[str, float | int | None]:
    hits = sum(int(item.get("prompt_cache_hit_tokens") or 0) for item in values)
    misses = sum(int(item.get("prompt_cache_miss_tokens") or 0) for item in values)
    total = hits + misses
    latencies = [int(item["latency_ms"]) for item in values if item.get("latency_ms") is not None]
    return {
        "call_count": len(values),
        "prompt_cache_hit_tokens": hits,
        "prompt_cache_miss_tokens": misses,
        "prompt_cache_hit_rate": hits / total if total else None,
        "average_latency_ms": fmean(latencies) if latencies else None,
        "retry_count": sum(int(item.get("retry_count") or 0) for item in values),
        "response_repair_count": sum(
            int(item.get("response_repair_count") or 0) for item in values
        ),
    }


def _load_model_metrics(capture: dict[str, object]) -> list[dict[str, object]]:
    database = Path(str(capture["database_path"]))
    session_id = SessionId(UUID(str(capture["session_id"])))
    events = tuple(SQLiteEventStore(database).list_for_session(session_id))
    return [
        {
            "prompt_cache_hit_tokens": call.prompt_cache_hit_tokens,
            "prompt_cache_miss_tokens": call.prompt_cache_miss_tokens,
            "latency_ms": call.latency_ms,
            "retry_count": call.retry_count,
            "response_repair_count": call.response_repair_count,
            "cache_boundary": call.cache_boundary.value,
        }
        for call in build_trace_record(events).model_calls
    ]


if __name__ == "__main__":
    raise SystemExit(main())
