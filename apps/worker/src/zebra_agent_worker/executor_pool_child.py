"""Long-lived executor pool child: amortize per-task boot cost (CA-HA-03 D6).

Protocol (stdin/stdout, one JSON object per line):
  Worker → child: {"op":"assign","task_id":...,"request":{...}}
  child → Worker: {"op":"ack","task_id":...}
  child → Worker: {"op":"result","task_id":...,"outcome":...,"result":...}
  child → Worker: {"op":"ready"}

One-time: parent fence, imports, settings, cloud composition (incl. TLS check).
Per-task: fresh postgres pool scope + execution service + execution.
Cancellation: SIGUSR1 sets a flag checked at execution safe points.
"""

import json
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from time import monotonic_ns
from typing import Any

logger = logging.getLogger(__name__)

_CANCEL = threading.Event()


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()


def _on_cancel(signum: int, frame: object) -> None:
    _CANCEL.set()


def _execute_pooled_task(
    settings: Any,
    cloud: Any,
    request: dict[str, Any],
    cancelled: threading.Event,
) -> dict[str, Any]:
    """Execute one task with a fresh service; returns serializable ExecutedSession."""
    from agent_core.domain.leases import LeaseLostError, WorkerLease
    from agent_storage.postgres.connection_pool import postgres_pool_scope
    from agent_storage.postgres.leases import PostgresLeaseStore
    from pydantic import TypeAdapter

    from zebra_agent_worker.claims import ClaimedSession
    from zebra_agent_worker.execution_events import ExecutionInterrupted
    from zebra_agent_worker.execution_finalization import ExecutedSession
    from zebra_agent_worker.execution_preparation import (
        recover_fenced_session as recover_initial_session,
    )
    from zebra_agent_worker.execution_recovery import execute_claimed_with_stale_retry
    from zebra_agent_worker.loop import build_worker_loop_service
    from zebra_agent_worker.worker_budget import BudgetExecutionCheck

    factory = request["factory"]
    bundle = None
    with postgres_pool_scope(settings.database_url, component="executor"):
        if factory != "default":
            import importlib

            module, name = factory.split(":")
            bundle = getattr(importlib.import_module(module), name)(settings, cloud)
        service = build_worker_loop_service(
            database_path=Path(settings.database_url),
            settings=settings,
            cloud_worker_composition=bundle,
            cloud_composition=cloud,
            model_http_client=None,
            execution_only=True,
        )._execution_service

        lease = WorkerLease.model_validate(request["lease"])
        try:
            recovery = recover_initial_session(service._recovery_service, lease)
        except Exception as error:
            logger.warning(
                "pool_child_recovery_failed session_id=%s fence=%s error=%s cause=%s",
                lease.session_id, lease.fence.fencing_token,
                type(error).__name__, type(error.__cause__).__name__,
            )
            raise

        claimed = ClaimedSession(lease=lease, recovery=recovery)
        lease_store = service._claim_service._lease_store

        def require_owned() -> None:
            if cancelled.is_set():
                raise ExecutionInterrupted("session cancelled; pool child received SIGUSR1")
            current = lease_store.get(lease.session_id)
            if current is None or current.fence != lease.fence:
                raise LeaseLostError("isolated executor fence revoked")

        result = execute_claimed_with_stale_retry(
            service,
            claimed,
            started_at=__import__("datetime").datetime.fromisoformat(request["executed_at"]),
            ownership_check=BudgetExecutionCheck(
                require_owned,
                ownership_database=(
                    lease_store._database if type(lease_store) is PostgresLeaseStore else None
                ),
            ),
        )
        # Serialize ExecutedSession to JSON-compatible dict
        dumped: dict[str, Any] = json.loads(TypeAdapter(ExecutedSession).dump_json(result))
        return dumped


def pool_main(worker_pid: int) -> None:
    """Entry point: one-time setup, then per-task loop on stdin."""
    from agent_runtime.executor_supervisor import parent_fence

    parent_fence(worker_pid, death_signal=signal.SIGTERM)

    # One-time heavy setup (imports, TLS check, composition)
    from agent_storage import cloud_composition_from_environment
    from zebra_agent_config import load_settings

    from zebra_agent_worker.session_process import settings_digest

    settings = load_settings()
    if settings.deployment != "cloud" or settings.storage_authority != "postgresql":
        raise ValueError("pool child requires cloud PostgreSQL composition")
    cloud = cloud_composition_from_environment()
    digest = settings_digest(settings)

    signal.signal(signal.SIGUSR1, _on_cancel)
    signal.signal(signal.SIGTERM, lambda s, f: os._exit(0))
    signal.signal(signal.SIGINT, lambda s, f: os._exit(0))

    logger.info("pool_child_ready pid=%s settings_digest=%s", os.getpid(), digest[:16])
    _emit({"op": "boot", "pid": os.getpid(), "settings_digest": digest})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("pool_child_bad_line length=%d", len(line))
            continue
        if message.get("op") != "assign":
            continue

        task_id = message.get("task_id", "")
        request = message.get("request", {})
        _CANCEL.clear()
        _emit({"op": "ack", "task_id": task_id})
        started = monotonic_ns()

        if settings_digest(settings) != request.get("settings_digest"):
            _emit({"op": "result", "task_id": task_id, "outcome": "settings_mismatch"})
            _emit({"op": "ready"})
            continue

        try:
            result = _execute_pooled_task(settings, cloud, request, _CANCEL)
            elapsed = (monotonic_ns() - started) // 1_000_000
            logger.info("pool_child_task_done task=%s elapsed_ms=%s", task_id, elapsed)
            _emit({"op": "result", "task_id": task_id, "outcome": "executed", "result": result})
        except Exception as error:
            logger.warning(
                "pool_child_task_failed task=%s error=%s", task_id, type(error).__name__
            )
            _emit({"op": "result", "task_id": task_id, "outcome": type(error).__name__})

        _emit({"op": "ready"})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    pool_main(int(sys.argv[1]))
