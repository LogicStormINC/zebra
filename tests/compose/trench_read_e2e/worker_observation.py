"""QA-only read-only process observation; the production Worker entrypoint is unchanged.

ponytail: global counts gate a quiescent single-worker cohort, not per-Task
attribution during concurrency. Inspect bounded stacks, never export local values.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import FrameType
from typing import Any, cast

SCHEMA = "zebra.qa-worker-observation.v1"
MODEL_MODULES = {
    "agent_integrations.openai_compatible",
    "agent_integrations.openai_streaming",
    "agent_integrations.deepseek_beta",
    "agent_integrations.deepseek_responses",
    "agent_integrations.deepseek_responses_streaming",
    "agent_integrations.bounded_model_http",
}


def observe() -> dict[str, Any]:
    threads, frames = threading.enumerate(), sys._current_frames()
    sample: dict[str, Any] = {
        "schema_version": SCHEMA,
        "pid": os.getpid(),
        "sample_monotonic": time.monotonic(),
        "coverage_complete": len(threads) <= 256 and len(frames) <= 256,
        "execution_threads": 0,
        "model_threads": 0,
        "public_wait_timers": 0,
        "text_flush_timers": 0,
        "lease_heartbeat_threads": 0,
    }
    for thread in threads[:256]:
        if thread.is_alive() and thread.name.startswith("lease-heartbeat-"):
            sample["lease_heartbeat_threads"] += 1
        if isinstance(thread, threading.Timer) and thread.is_alive():
            module = getattr(thread.function, "__module__", "")
            if module == "agent_core.harness.public_output":
                sample["public_wait_timers"] += 1
            elif module == "agent_core.harness.stream_deltas":
                sample["text_flush_timers"] += 1
        frame: FrameType | None = frames.get(thread.ident) if thread.ident is not None else None
        execution = model = False
        for _ in range(256):
            if frame is None:
                break
            module = frame.f_globals.get("__name__", "")
            model |= module in MODEL_MODULES
            execution |= (
                module == "zebra_agent_worker.execution"
                and frame.f_code.co_name == "_execute_claimed_session_once"
            )
            frame = frame.f_back
        if frame is not None:
            sample["coverage_complete"] = False
        sample["model_threads"] += int(model)
        sample["execution_threads"] += int(execution)
    return sample


class ObservationHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/observation":
            self.send_error(404)
            return
        body = json.dumps(observe()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass  # No request bodies, stack values, environment or URLs enter evidence/logs.


def main() -> int:
    worker_main = cast(Callable[[], int], importlib.import_module("zebra_agent_worker.main").main)

    server = HTTPServer(("127.0.0.1", 9097), ObservationHandler)
    observer = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.05},
        daemon=True,
        name="qa-readonly-observation",
    )
    observer.start()
    try:
        return worker_main()
    finally:
        server.shutdown()
        server.server_close()
        observer.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
