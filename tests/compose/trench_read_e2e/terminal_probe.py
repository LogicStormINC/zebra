"""Actual bounded terminal proof: canonical commit + scalar state + live Worker counts."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from support import Config, E2EError

COUNTERS = (
    "execution_threads",
    "model_threads",
    "public_wait_timers",
    "text_flush_timers",
    "lease_heartbeat_threads",
)
CLEANUP_SECONDS = 5.0


def terminal_clean(native: Mapping[str, Any], worker: Mapping[str, Any]) -> bool:
    return (
        native.get("final_count") == 1
        and native.get("status") in {"completed", "awaiting_turn"}
        and native.get("lease_released") is True
        and worker.get("schema_version") == "zebra.qa-worker-observation.v1"
        and worker.get("coverage_complete") is True
        and all(type(worker.get(key)) is int and worker[key] == 0 for key in COUNTERS)
    )


def cleanup_deadline(answer_observed_at: float, budget_seconds: float) -> float:
    if not 0 < budget_seconds <= CLEANUP_SECONDS:
        raise ValueError("invalid_cleanup_budget")
    deadline = answer_observed_at + budget_seconds
    if time.monotonic() >= deadline:
        raise TimeoutError("cleanup_deadline_expired")
    return deadline


def native_terminal(config: Config, task: str, run_id: str, deadline: float) -> dict[str, Any]:
    from agent_core.domain.identifiers import TaskId
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.task_replay_headers import read_run_header

    # The caller proves namespace/DSNs/containers before the first query. Indexed scalars only.
    manifest = json.loads(Path(config.isolation_manifest).read_text())
    scope = manifest["namespace_id"]
    db = PostgresDatabase(config.zebra_database_dsn, deployment_namespace=scope)
    with db.connect_task_io(deadline=min(deadline, time.monotonic() + 2)) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        header = read_run_header(connection, scope, TaskId(UUID(task)), run_id, None)
        if header.anchor is None or header.control_only:
            raise E2EError("cleanup_run_not_canonical")
        rows = connection.execute(
            "SELECT event_id,event_type FROM session_events WHERE deployment_namespace=%s "
            "AND task_id=%s AND task_sequence BETWEEN %s AND %s "
            "ORDER BY task_sequence LIMIT 257",
            (scope, task, header.start, header.stop - 1 if header.stop else header.highwater),
        ).fetchall()
        if len(rows) > 256:
            raise E2EError("cleanup_run_header_evidence_limit")
        finals = [row for row in rows if row["event_type"] == "answer_committed"]
        row = connection.execute(
            "SELECT h.status,t.active_segment_id,l.released_at IS NOT NULL AS lease_released "
            "FROM agent_tasks t JOIN session_observation_headers h "
            "ON h.deployment_namespace=t.deployment_namespace "
            "AND h.session_id=t.active_segment_id::text LEFT JOIN worker_leases l "
            "ON l.deployment_namespace=t.deployment_namespace AND l.session_id=t.active_segment_id "
            "WHERE t.deployment_namespace=%s AND t.task_id=%s",
            (scope, task),
        ).fetchone()
    return {
        "final_count": len(finals),
        "final_event_ids": [str(row["event_id"]) for row in finals],
        "run_id": run_id,
        "status": row["status"] if row else None,
        "lease_released": row["lease_released"] if row else False,
        "active_segment_id": str(row["active_segment_id"]) if row else None,
        "body_hydration": False,
    }


def live_worker(config: Config, deadline: float) -> dict[str, Any]:
    from scratch_topology import docker

    manifest = json.loads(Path(config.isolation_manifest).read_text())
    worker_id = manifest["containers"]["worker"]["id"]
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("cleanup_deadline_expired")
    code = (
        "import urllib.request;"
        "r=urllib.request.urlopen('http://127.0.0.1:9097/observation',timeout=1);"
        "print(r.read(8193).decode())"
    )
    value = docker(["exec", worker_id, "python", "-c", code], timeout=min(2, remaining))
    if len(value) > 8192:
        raise E2EError("worker_observation_oversized")
    return cast(dict[str, Any], json.loads(value))


def prove_cleanup(config: Config, conversation_key: str, run_id: str) -> dict[str, Any]:
    from isolation import joint_preflight
    from support import task_binding

    started = time.monotonic()
    deadline = cleanup_deadline(started, CLEANUP_SECONDS)
    joint_preflight(config)
    task, _thread = task_binding(config, conversation_key=conversation_key, simple_slice=True)
    consecutive = 0
    samples: list[dict[str, Any]] = []
    while time.monotonic() < deadline and len(samples) < 32:
        native = native_terminal(config, task, run_id, deadline)
        worker = live_worker(config, deadline)
        clean = terminal_clean(native, worker)
        consecutive = consecutive + 1 if clean else 0
        samples.append(
            {
                "after_probe_start_ms": (time.monotonic() - started) * 1000,
                "native": native,
                "worker": worker,
                "clean": clean,
            }
        )
        if consecutive == 2:
            return {
                "scope": "native_readonly_pg_and_same_worker_process",
                "task_id": task,
                "status": "passed",
                "samples": samples,
                "budget_seconds": CLEANUP_SECONDS,
                "cohort_quiescent_gate": True,
            }
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    raise E2EError("terminal_cleanup_not_proven_within_budget")


def main() -> int:
    from run_acceptance import REQUIRED_ENV
    from support import load_config

    try:
        inputs = dict(os.environ)
        for key in ("TRENCH_E2E_BUSINESS_SNAPSHOT_URL", "ZEBRA_E2E_WORKER_RESTART_URL"):
            inputs.setdefault(key, inputs.get("TRENCH_E2E_BFF_URL", ""))
        inputs.setdefault("TRENCH_E2E_EVENT_ID", "unused_in_cleanup")
        config = load_config(inputs, REQUIRED_ENV)
        argument = json.loads(sys.stdin.read(1024))
        result = prove_cleanup(config, argument["conversation_key"], argument["run_id"])
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps({"status": "failed", "reason": "terminal_cleanup_unproven"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
