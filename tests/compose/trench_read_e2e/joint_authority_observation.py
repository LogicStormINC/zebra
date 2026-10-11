"""Read-only canonical pending approval identity, before any QA operator decision."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Mapping
from typing import Any

from isolation import joint_preflight
from joint_worker_takeover import native_execution
from support import Config, E2EError, task_binding


def pending_approval(native: Mapping[str, Any]) -> dict[str, Any] | None:
    if native.get("status") != "waiting_approval":
        if native.get("status") not in {"running", "queued", "ready"}:
            raise E2EError("authority_approval_no_longer_pending")
        return None
    rows = native.get("rows", [])
    pending = [r for r in rows if r["event_type"] == "approval_requested"]
    if len(pending) != 1:
        raise E2EError("authority_one_exact_pending_approval_required")
    point = pending[0]
    if (
        not isinstance(point.get("call"), str)
        or not 0 < len(point["call"]) <= 256
        or not re.fullmatch(r"[a-f0-9]{64}", point.get("fingerprint") or "")
        or any(
            r["event_type"] in {"approval_granted", "approval_rejected"}
            or r.get("call") == point["call"]
            and r["event_type"].startswith("tool_execution_")
            for r in rows
        )
    ):
        raise E2EError("authority_pending_approval_identity_or_execution_invalid")
    return {
        "event_id": point["event_id"],
        "tool_call_id": point["call"],
        "call_fingerprint": point["fingerprint"],
    }


def observe_approval(config: Config, inputs: Mapping[str, str]) -> dict[str, Any]:
    from agent_storage.postgres.database import PostgresDatabase

    proof = joint_preflight(config)
    task, _ = task_binding(config, conversation_key=inputs["conversation_key"], simple_slice=True)
    deadline = time.monotonic() + 2
    try:
        native = native_execution(config, task, inputs["run_id"], deadline)
    except E2EError as exc:
        if exc.code == "takeover_claim_not_observed":
            return {"status": "preparing"}
        raise
    pending = pending_approval(native)
    if pending is None:
        return {"status": "preparing"}
    scope = str(proof["namespace_id"])
    # Match the existing projector's message preference and fixed default, not invented prose.
    message_sql = (
        "COALESCE(NULLIF(payload->>'assistant_message',''),"
        "NULLIF(payload->>'reason',''),'Approval is required.')"
    )
    with PostgresDatabase(config.zebra_database_dsn, deployment_namespace=scope).connect_task_io(
        deadline=deadline
    ) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        key = (scope, pending["event_id"])
        where = " FROM session_events WHERE deployment_namespace=%s AND event_id=%s"
        size = c.execute("SELECT octet_length(" + message_sql + ") AS n" + where, key).fetchone()
        if size is None or not 0 < size["n"] <= 8192:
            raise E2EError("authority_approval_message_limit")
        row = c.execute("SELECT " + message_sql + " AS message" + where, key).fetchone()
        if row is None:
            raise E2EError("authority_approval_message_missing")
    return {"status": "ready", **inputs, "task_id": task, **pending, "message": row["message"]}


def main() -> int:
    from run_acceptance import REQUIRED_ENV
    from support import load_config

    try:
        if os.environ.get("ZEBRA_E2E_P1_FROZEN") != "1":
            raise E2EError("authority_latest_build_freeze_required")
        raw = sys.stdin.read(8193)
        if len(raw.encode()) > 8192:
            raise E2EError("authority_observer_input_limit")
        inputs = json.loads(raw)
        if set(inputs) != {"conversation_key", "run_id", "turn_id"} or any(
            not isinstance(v, str) or not 0 < len(v) <= 256 for v in inputs.values()
        ):
            raise E2EError("authority_observer_input_invalid")
        print(json.dumps(observe_approval(load_config(os.environ, REQUIRED_ENV), inputs)))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": exc.code
                    if isinstance(exc, E2EError)
                    else "authority_observer_unproven",
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
