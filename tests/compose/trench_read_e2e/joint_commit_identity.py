"""QA-only exact admitted Turn -> bound Task -> canonical Run scan floor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from agent_core.domain.identifiers import TaskId
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_replay_headers import read_run_header
from isolation import joint_preflight
from support import Config, E2EError, load_config, task_binding


def initialize_identity(config: Config, request: dict[str, Any]) -> dict[str, Any]:
    if set(request) != {"conversation_key", "run_id", "turn_id"}:
        raise ValueError("exact_admission_coordinates_required")
    conversation, run, turn = (request[name] for name in ("conversation_key", "run_id", "turn_id"))
    if (
        not isinstance(conversation, str)
        or not 0 < len(conversation) <= 256
        or "::" in conversation
    ):
        raise ValueError("invalid_conversation")
    if not isinstance(run, str) or not 0 < len(run) <= 256:
        raise ValueError("invalid_run")
    turn = str(UUID(turn))
    namespace = joint_preflight(config)["namespace_id"]
    if not isinstance(namespace, str) or not namespace:
        raise ValueError("namespace_unverified")
    # Turn PK lookup prevents mixing one Turn with another Run on the same Task.
    with psycopg.connect(
        config.trench_database_dsn,
        connect_timeout=2,
        options="-c default_transaction_read_only=on -c statement_timeout=2000 -c lock_timeout=500",
    ) as c:
        row = c.execute(
            "SELECT run_id FROM trench_ai_turns WHERE turn_id=%s "
            "AND conversation_key=%s AND user_id=%s AND workspace_id=%s",
            (
                turn,
                f"trench_ai::{config.user_id}::{config.workspace_id}::{conversation}",
                config.user_id,
                config.workspace_id,
            ),
        ).fetchone()
        if row is None or row[0] != run:
            raise ValueError("admitted_turn_run_mismatch")
    try:
        task, _ = task_binding(config, conversation_key=conversation, simple_slice=True)
    except E2EError as exc:
        if exc.code != "trench_task_binding_unavailable":
            raise
        return {"status": "preparing", "reason": "task_binding_not_visible", **request}
    database = PostgresDatabase(config.zebra_database_dsn, deployment_namespace=namespace)
    with database.connect_task_io() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY")
        header = read_run_header(c, namespace, TaskId(UUID(task)), run, None)
    if header.anchor is None:
        return {
            "status": "preparing",
            "reason": "canonical_run_not_visible",
            "task_id": task,
            **request,
        }
    if header.control_only or header.legacy:
        raise ValueError("executable_canonical_run_required")
    return {
        "status": "ready",
        "task_id": task,
        "deployment_namespace": namespace,
        "after_sequence": header.start - 1,
        "anchor_event_id": str(header.anchor.event_id),
        "floor_basis": "canonical_run_anchor_minus_one",
        "absence_proof": False,
        **request,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    args = parser.parse_args()
    try:
        from run_acceptance import REQUIRED_ENV

        if args.inputs.stat().st_size > 32768 or args.inputs.stat().st_mode & 0o077:
            raise ValueError("private_bounded_inputs_required")
        inputs = json.loads(args.inputs.read_text())
        for key in ("TRENCH_E2E_BUSINESS_SNAPSHOT_URL", "ZEBRA_E2E_WORKER_RESTART_URL"):
            inputs.setdefault(key, inputs["TRENCH_E2E_BFF_URL"])
        inputs.setdefault("TRENCH_E2E_EVENT_ID", "unused_in_commit_identity")
        raw = sys.stdin.readline(8193)
        if len(raw) > 8192 or not raw.endswith("\n"):
            raise ValueError("bounded_admission_line_required")
        result = initialize_identity(load_config(inputs, REQUIRED_ENV), json.loads(raw))
        print(json.dumps(result, allow_nan=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "invalid", "reason": "commit_identity_" + type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
