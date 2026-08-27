from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx
from agent_core.domain.sessions import SessionStatus
from zebra_agent_config import load_settings

from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.loop import WorkerLoopService, build_worker_loop_service
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.resume import SessionResumeService


def worker_banner() -> str:
    return f"worker-ready:{SessionStatus.CREATED.value}"


def main(argv: Sequence[str] | None = None) -> int:
    namespace = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_settings()
    database_path = Path(namespace.database or settings.database_url)
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as model_http_client:
        loop_service = build_worker_loop_service(
            database_path=database_path,
            settings=settings,
            model_http_client=model_http_client,
        )
        result = loop_service.run(
            worker_id=namespace.worker_id,
            batch_size=namespace.batch_size,
            lease_ttl_seconds=namespace.lease_ttl_seconds,
            max_cycles=namespace.max_cycles,
            stop_when_idle=namespace.stop_when_idle,
            idle_sleep_seconds=namespace.idle_sleep_seconds,
        )
    print(
        json.dumps(
            {
                "command": "loop",
                "database": str(database_path),
                "worker_id": namespace.worker_id,
                "batch_size": namespace.batch_size,
                "lease_ttl_seconds": namespace.lease_ttl_seconds,
                "max_cycles": namespace.max_cycles,
                "stop_when_idle": namespace.stop_when_idle,
                "cycles_completed": result.cycles_completed,
                "idle_cycles": result.idle_cycles,
                "stop_reason": result.stop_reason,
                "executed_session_ids": list(result.executed_session_ids),
                "skipped_session_ids": list(result.skipped_session_ids),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zebra-agent-worker")
    parser.add_argument(
        "--database",
        default=None,
        help=(
            "Local SQLite database path. Cloud profile ignores this path and "
            "uses ZEBRA_DATABASE_URL. Defaults to settings database_url."
        ),
    )
    parser.add_argument(
        "--worker-id",
        default="local-worker",
        help="Worker identity used for durable session leases.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Maximum number of ready sessions to inspect per cycle.",
    )
    parser.add_argument(
        "--lease-ttl-seconds",
        type=int,
        default=30,
        help="Lease TTL used for each claimed session.",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Maximum number of polling cycles to run. Omit for continuous operation.",
    )
    parser.add_argument(
        "--stop-when-idle",
        action="store_true",
        help="Stop after the first idle cycle instead of continuing to poll.",
    )
    parser.add_argument(
        "--idle-sleep-seconds",
        type=float,
        default=1.0,
        help="Sleep duration between idle polls when not stopping.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "SessionClaimService",
    "SessionRecoveryService",
    "SessionResumeService",
    "WorkerLoopService",
    "main",
    "worker_banner",
]
