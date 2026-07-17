from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from agent_core.domain.events import EventType

from agent_observability.models import (
    AuditRecord,
    CostSummary,
    ProviderModelCallTrace,
    TraceRecord,
)


@dataclass(frozen=True)
class JsonlTraceStore:
    path: Path

    def append(self, trace: TraceRecord) -> None:
        if self.path.exists() and self.path.is_dir():
            raise ValueError("trace store path must not be a directory")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_trace_to_json(trace), sort_keys=True) + "\n")

    def list(self) -> tuple[TraceRecord, ...]:
        if not self.path.exists():
            return ()
        if self.path.is_dir():
            raise ValueError("trace store path must not be a directory")
        traces: list[TraceRecord] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    traces.append(_trace_from_json(json.loads(stripped)))
        return tuple(traces)


def _trace_to_json(trace: TraceRecord) -> dict[str, object]:
    return {
        "session_id": trace.session_id,
        "event_count": trace.event_count,
        "tool_result_count": trace.tool_result_count,
        "cost": asdict(trace.cost),
        "audit": [
            {
                "sequence": record.sequence,
                "event_type": record.event_type.value,
                "actor": record.actor,
                "summary": record.summary,
            }
            for record in trace.audit
        ],
        "model_calls": [asdict(record) for record in trace.model_calls],
    }


def _trace_from_json(value: object) -> TraceRecord:
    if not isinstance(value, dict):
        raise ValueError("trace json line must be an object")
    raw_cost = value.get("cost")
    if not isinstance(raw_cost, dict):
        raise ValueError("trace json line must include cost object")
    raw_audit = value.get("audit")
    if not isinstance(raw_audit, list):
        raise ValueError("trace json line must include audit list")
    raw_model_calls = value.get("model_calls", [])
    if not isinstance(raw_model_calls, list):
        raise ValueError("trace json line model_calls must be a list")
    return TraceRecord(
        session_id=_read_str(value, "session_id"),
        event_count=_read_int(value, "event_count"),
        tool_result_count=_read_int(value, "tool_result_count"),
        cost=CostSummary(
            model_calls=_read_int(raw_cost, "model_calls"),
            input_tokens=_read_int(raw_cost, "input_tokens"),
            output_tokens=_read_int(raw_cost, "output_tokens"),
            total_tokens=_read_int(raw_cost, "total_tokens"),
            cost_usd=_read_float(raw_cost, "cost_usd"),
            reasoning_tokens=_read_optional_int(raw_cost, "reasoning_tokens") or 0,
            prompt_cache_hit_tokens=(_read_optional_int(raw_cost, "prompt_cache_hit_tokens") or 0),
            prompt_cache_miss_tokens=(
                _read_optional_int(raw_cost, "prompt_cache_miss_tokens") or 0
            ),
        ),
        audit=tuple(_audit_from_json(item) for item in raw_audit),
        model_calls=tuple(_model_call_from_json(item) for item in raw_model_calls),
    )


def _model_call_from_json(value: object) -> ProviderModelCallTrace:
    if not isinstance(value, dict):
        raise ValueError("model call trace must be an object")
    return ProviderModelCallTrace(
        sequence=_read_int(value, "sequence"),
        profile_id=_read_optional_str(value, "profile_id"),
        profile_version_observed_at=_read_optional_str(value, "profile_version_observed_at"),
        provider=_read_optional_str(value, "provider"),
        requested_model=_read_optional_str(value, "requested_model"),
        resolved_model=_read_optional_str(value, "resolved_model"),
        role=_read_optional_str(value, "role"),
        thinking_mode=_read_optional_str(value, "thinking_mode"),
        reasoning_effort=_read_optional_str(value, "reasoning_effort"),
        tool_choice=_read_optional_str(value, "tool_choice"),
        prompt_version=_read_optional_str(value, "prompt_version"),
        tool_schema_bytes=_read_optional_int(value, "tool_schema_bytes"),
        tool_schema_hash=_read_optional_str(value, "tool_schema_hash"),
        stable_prefix_hash=_read_optional_str(value, "stable_prefix_hash"),
        input_tokens=_read_optional_int(value, "input_tokens"),
        output_tokens=_read_optional_int(value, "output_tokens"),
        reasoning_tokens=_read_optional_int(value, "reasoning_tokens"),
        prompt_cache_hit_tokens=_read_optional_int(value, "prompt_cache_hit_tokens"),
        prompt_cache_miss_tokens=_read_optional_int(value, "prompt_cache_miss_tokens"),
        cost_usd=_read_optional_float(value, "cost_usd"),
        finish_reason=_read_optional_str(value, "finish_reason"),
        time_to_first_event_ms=_read_optional_int(value, "time_to_first_event_ms"),
        time_to_first_public_text_ms=_read_optional_int(value, "time_to_first_public_text_ms"),
        latency_ms=_read_optional_int(value, "latency_ms"),
        retry_count=_read_optional_int(value, "retry_count") or 0,
        normalized_error=_read_optional_str(value, "normalized_error"),
        system_fingerprint=_read_optional_str(value, "system_fingerprint"),
    )


def _audit_from_json(value: object) -> AuditRecord:
    if not isinstance(value, dict):
        raise ValueError("audit item must be an object")
    return AuditRecord(
        sequence=_read_int(value, "sequence"),
        event_type=EventType(_read_str(value, "event_type")),
        actor=_read_str(value, "actor"),
        summary=_read_str(value, "summary"),
    )


def _read_str(value: dict[object, object], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str):
        raise ValueError(f"trace field {key} must be a string")
    return raw


def _read_int(value: dict[object, object], key: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"trace field {key} must be an integer")
    return raw


def _read_float(value: dict[object, object], key: str) -> float:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError(f"trace field {key} must be a number")
    return float(raw)


def _read_optional_int(value: dict[object, object], key: str) -> int | None:
    raw = value.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"trace field {key} must be an integer")
    return raw


def _read_optional_str(value: dict[object, object], key: str) -> str | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"trace field {key} must be a string")
    return raw


def _read_optional_float(value: dict[object, object], key: str) -> float | None:
    raw = value.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError(f"trace field {key} must be a number")
    return float(raw)
