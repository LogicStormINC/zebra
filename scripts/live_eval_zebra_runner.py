from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_observability import build_trace_record
from agent_storage import SQLiteEventStore
from live_eval_fixture import materialize, workspace_digest


def main() -> int:
    request = json.load(sys.stdin)
    case = request["case"]
    repetition = int(request["repetition"])
    case_id = str(case["case_id"])
    evidence_root = Path(os.environ.get("ZEBRA_LIVE_EVAL_ROOT", "evals/live/runs")).resolve()
    attempt_id = f"{case_id}-r{repetition}-{uuid.uuid4().hex[:12]}"
    workspace = evidence_root / attempt_id / "workspace"
    workspace.mkdir(parents=True)
    spec = materialize(case, workspace)
    subprocess.run(
        ("git", "init", "--quiet"),
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    initial_digest = workspace_digest(workspace)
    database = evidence_root / attempt_id / "session.sqlite"
    prompt = (
        f"{case['prompt']}\n\nFixture instructions: {spec.instructions}\n"
        f"Work only inside {workspace}. Use tools to inspect and verify before concluding."
    )
    category = str(case["category"])
    tool_profile = (
        "coding" if category == "code" else "research" if category == "research" else "general"
    )
    policy = "read_only" if category in {"answer", "research"} else "workspace_write"
    started = datetime.now(UTC)
    start = time.monotonic()
    completed = subprocess.run(
        [
            "uv",
            "run",
            "zebra-agent",
            "run",
            prompt,
            "--title",
            f"live-eval {case_id} r{repetition}",
            "--execute",
            "--workspace",
            str(workspace),
            "--database",
            str(database),
            "--policy-profile",
            policy,
            "--tool-profile",
            tool_profile,
            "--network-profile",
            "none",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    duration_ms = round((time.monotonic() - start) * 1000)
    finished = datetime.now(UTC)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-2000:])
    result = json.loads(completed.stdout)
    session_id = SessionId(UUID(str(result["session_id"])))
    domain_events = tuple(SQLiteEventStore(database).list_for_session(session_id))
    events = [
        {
            "sequence": event.sequence,
            "event_type": event.event_type.value,
            "payload": event.payload,
            "created_at": event.created_at.isoformat(),
        }
        for event in domain_events
    ]
    model_events = [event for event in events if event["event_type"] == "model_response_received"]
    model_call_ids = [str(event["payload"]["model_call_id"]) for event in model_events]
    if not model_call_ids:
        raise RuntimeError("real Zebra run produced no authoritative model call ids")
    ttft = min(
        int(event["payload"].get("time_to_first_public_text_ms") or duration_ms)
        for event in model_events
    )
    costs = [event["payload"].get("cost_usd") for event in model_events]
    trace_calls = build_trace_record(domain_events).model_calls
    model_metrics = [
        {
            "model_call_id": event["payload"]["model_call_id"],
            "input_tokens": event["payload"].get("input_tokens"),
            "output_tokens": event["payload"].get("output_tokens"),
            "prompt_cache_hit_tokens": event["payload"].get("prompt_cache_hit_tokens"),
            "prompt_cache_miss_tokens": event["payload"].get("prompt_cache_miss_tokens"),
            "latency_ms": event["payload"].get("latency_ms"),
            "retry_count": event["payload"].get("retry_count"),
            "response_repair_count": event["payload"].get("response_repair_count"),
            "response_stage": event["payload"].get("response_stage"),
            "cache_boundary": trace.cache_boundary.value,
        }
        for event, trace in zip(model_events, trace_calls, strict=True)
    ]
    tool_signatures = [
        (
            event["payload"].get("tool_name"),
            json.dumps(event["payload"].get("arguments"), sort_keys=True),
        )
        for event in events
        if event["event_type"] == "tool_execution_completed"
    ]
    status = str(result["status"])
    terminal = (
        "completed"
        if status == "completed"
        else "blocked"
        if status in {"suspended", "awaiting_approval", "awaiting_input"}
        else "failed"
    )
    capture = {
        "attempt_id": attempt_id,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "session_id": result["session_id"],
        "turn_id": result["session_id"],
        "model_call_ids": model_call_ids,
        "case_category": category,
        "model_metrics": model_metrics,
        "terminal_outcome": terminal,
        "completion_claimed": status == "completed",
        # Automated process recovery is measured separately from human intervention.
        "human_intervention": False,
        "runner_failures_before_capture": int(
            os.environ.get("ZEBRA_LIVE_EVAL_PRIOR_RUNNER_FAILURES", "0")
        ),
        "repeated_tool_calls": len(tool_signatures) - len(set(tool_signatures)),
        "first_public_feedback_ms": min(ttft, duration_ms),
        "total_duration_ms": duration_ms,
        "cost_usd": sum(float(value) for value in costs)
        if costs and all(value is not None for value in costs)
        else None,
        "assistant_message": result.get("assistant_message") or "",
        "database_path": str(database),
        "workspace_path": str(workspace),
        "initial_fixture_sha256": initial_digest,
        "final_workspace_sha256": workspace_digest(workspace),
        "event_count": len(events),
        "stop_reason": result.get("stop_reason"),
    }
    print(json.dumps(capture, ensure_ascii=False, sort_keys=True))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
