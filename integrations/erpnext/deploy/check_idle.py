"""Read-only restart gate. Run on the server after pausing new admissions.

This is a conservative deployment check, never a cancellation/recovery command.
"""
import json
import subprocess
import sys

IDLE = {"completed", "failed", "cancelled", "stopped", "suspended", "waiting_input",
        "awaiting_turn", "awaiting_input", "awaiting_approval", "blocked", "partial"}


def require_idle(counts):
    busy = {status: count for status, count in counts.items() if count and status not in IDLE}
    if busy:
        raise RuntimeError("Refusing ERP restart; active or unknown task states: " + json.dumps(busy))


def main():
    if sys.argv[1:] == ["--self-check"]:
        require_idle({"completed": 2, "awaiting_turn": 1, "failed": 1})
        for status in ["ready", "created", "dispatching", "running", "queued", "waiting_client_effect", "unknown"]:
            try:
                require_idle({status: 1})
            except RuntimeError:
                continue
            raise AssertionError(status)
        print("PASS idle gate refuses active and unknown states")
        return
    if sys.argv[1:]:
        raise SystemExit("Usage: python3 deploy/check_idle.py [--self-check]")
    # ponytail: scalar counts intentionally include stale queued tasks. Never
    # expire/cancel them to permit a deploy; investigate the retained work first.
    sql = """SELECT coalesce(json_object_agg(status,n),'{}'::json) FROM (
      SELECT p.status,count(*) n FROM agent_tasks t JOIN session_projections p
      ON p.deployment_namespace=t.deployment_namespace AND p.session_id=t.active_segment_id
      WHERE t.deployment_namespace='erpnext' GROUP BY p.status) states"""
    raw = subprocess.check_output(["docker", "exec", "erpnext-agent-postgres-1", "psql",
        "-U", "erpnext_agent", "-d", "erpnext_agent", "-At", "-v", "ON_ERROR_STOP=1", "-c", sql], text=True)
    require_idle(json.loads(raw))
    print("PASS native task projections idle; keep admissions paused until deployment is verified")


if __name__ == "__main__":
    main()
