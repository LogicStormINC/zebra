from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from agent_core.domain.events import EventType

from agent_observability.models import AuditRecord, CostSummary, TraceRecord


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
        ),
        audit=tuple(_audit_from_json(item) for item in raw_audit),
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
