"""Trusted no-model operator factory used ONLY in an owned Linux acceptance container."""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import psycopg
from agent_storage.postgres.projections import PostgresProjectionStore
from zebra_agent_config import load_settings
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.session_process import execute_isolated


def compose(settings, cloud):
    # Stall at the real operator composition boundary, BEFORE model/gateway setup.
    # Keep the very locks that previously blocked ordinary direct cancellation.
    from agent_storage.postgres.leases import lock_session_lease_boundary

    with psycopg.connect(settings.database_url) as connection:
        sid = UUID(os.environ["FORCE_STOP_PROBE_SID"])
        lock_session_lease_boundary(connection, cloud.deployment_namespace, sid)
        connection.execute(
            "SELECT current_version FROM session_streams "
            "WHERE deployment_namespace=%s AND session_id=%s FOR UPDATE",
            (cloud.deployment_namespace, sid),
        )
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        detached = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(600)",
            ],
            start_new_session=True,
        )
        from pathlib import Path

        Path(f"/tmp/force-detached-{sid}").write_text(str(detached.pid))
        print("HUNG_FACTORY_READY", flush=True)
        while True:
            time.sleep(1)


def main():
    request = json.load(sys.stdin)
    os.environ.update(request["env"])
    os.environ["ZEBRA_SESSION_PROCESS_FACTORY"] = "tests.agent_runtime.force_stop_probe:compose"
    os.environ["FORCE_STOP_PROBE_SID"] = request["lease"]["session_id"]
    settings = load_settings()
    service = SimpleNamespace(
        _settings=settings,
        _projection_store=PostgresProjectionStore(
            settings.database_url, deployment_namespace=request["env"]["ZEBRA_DEPLOYMENT_NAMESPACE"]
        ),
    )
    from time import monotonic

    from agent_storage.postgres.database import postgres_deadline

    try:
        with postgres_deadline(monotonic() - 1):
            execute_isolated(
                service,
                {
                    "session_id": request["lease"]["session_id"],
                    "lease": request["lease"],
                    "executed_at": datetime.now(UTC).isoformat(),
                },
            )
    except ExecutionInterrupted:
        print(json.dumps({"parent_survived": True, "model_calls": 0}), flush=True)
        while True:
            time.sleep(1)
    else:
        raise AssertionError("hanging factory unexpectedly returned")


if __name__ == "__main__":
    main()
