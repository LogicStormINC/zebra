"""Private child entrypoint. Factory comes from operator configuration, not a Run."""

import importlib
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from agent_core.domain.leases import LeaseLostError, WorkerLease
from agent_storage import cloud_composition_from_environment
from agent_storage.postgres.connection_pool import postgres_pool_scope
from pydantic import TypeAdapter
from zebra_agent_config import load_settings

from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.execution_finalization import ExecutedSession
from zebra_agent_worker.execution_preparation import (
    recover_fenced_session as recover_initial_session,
)
from zebra_agent_worker.execution_recovery import execute_claimed_with_stale_retry
from zebra_agent_worker.loop import build_worker_loop_service
from zebra_agent_worker.session_process import settings_digest

logger = logging.getLogger(__name__)


def main() -> None:
    started = time.monotonic_ns()
    execute = len(sys.argv) > 1 and sys.argv[1] == "--execute"
    if sys.argv[1:] != ["--check"] and not execute:
        from agent_runtime.executor_supervisor import run

        run(Path(sys.argv[1]), Path(sys.argv[2]))
        return
    check = sys.argv[1:] == ["--check"]
    settings = load_settings()
    if check:
        request = {
            "factory": os.environ["ZEBRA_SESSION_PROCESS_FACTORY"],
            "settings_digest": settings_digest(settings),
        }
    else:
        request_path, result_path = map(Path, sys.argv[2:4])
        request = json.loads(request_path.read_bytes())
    if not check and sys.platform == "linux":
        from agent_runtime.executor_supervisor import parent_fence

        parent_fence(int(sys.argv[4]))
    if (
        settings.deployment != "cloud"
        or settings.storage_authority != "postgresql"
        or settings_digest(settings) != request["settings_digest"]
    ):
        raise ValueError("isolated execution configuration mismatch")
    cloud = cloud_composition_from_environment()
    if not check and cloud.deployment_namespace != request["deployment_namespace"]:
        raise ValueError("isolated execution namespace mismatch")
    factory = request["factory"]
    bundle = None
    with postgres_pool_scope(settings.database_url, component="executor"):
        if factory != "default":
            module, name = factory.split(":")
            bundle = getattr(importlib.import_module(module), name)(settings, cloud)
        service = build_worker_loop_service(
            database_path=Path(settings.database_url),
            settings=settings,
            cloud_worker_composition=bundle,
            cloud_composition=cloud,
            model_http_client=None,
        )._execution_service
        if check:
            print(
                json.dumps(
                    {
                        "cloud_composition_ready": True,
                        "run_executed": False,
                        "composition_ms": round((time.monotonic_ns() - started) / 1_000_000, 1),
                    }
                )
            )
            return
        composed = time.monotonic_ns()
        lease = WorkerLease.model_validate(request["lease"])
        # Parent alone owns heartbeat/release; avoid checkpoint races between processes.
        claimed = ClaimedSession(
            lease=lease,
            recovery=recover_initial_session(service._recovery_service, lease),
        )

        launch = os.environ.get("ZEBRA_SESSION_PROCESS_LAUNCH_NS", "")
        if launch.isascii() and launch.isdecimal() and len(launch) <= 20:
            logger.info(
                "worker_executor_recovered session_id=%s fence=%s "
                "launch_to_main_ms=%s composition_ms=%s recovery_ms=%s",
                lease.session_id, lease.fence.fencing_token,
                (started - int(launch)) // 1_000_000,
                (composed - started) // 1_000_000,
                (time.monotonic_ns() - composed) // 1_000_000,
            )

        def require_owned() -> None:
            current = service._claim_service._lease_store.get(lease.session_id)
            if current is None or current.fence != lease.fence:
                raise LeaseLostError("isolated executor fence revoked")

        result = execute_claimed_with_stale_retry(
            service,
            claimed,
            started_at=datetime.fromisoformat(request["executed_at"]),
            ownership_check=require_owned,
        )
        result_path.write_bytes(TypeAdapter(ExecutedSession).dump_json(result))


if __name__ == "__main__":
    main()
