"""Private child entrypoint. Factory comes from operator configuration, not a Run."""

import importlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from agent_core.domain.leases import LeaseLostError, WorkerLease
from agent_storage import cloud_composition_from_environment
from agent_storage.postgres.connection_pool import postgres_pool_scope
from pydantic import TypeAdapter
from zebra_agent_config import load_settings

from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.execution_errors import WorkerInputPreparationUnavailable
from zebra_agent_worker.execution_finalization import ExecutedSession
from zebra_agent_worker.execution_recovery import execute_claimed_with_stale_retry
from zebra_agent_worker.loop import build_worker_loop_service
from zebra_agent_worker.session_process import settings_digest, write_input_failure


def main() -> None:
    started = time.monotonic()
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
    if factory != "default":
        module, name = factory.split(":")
        bundle = getattr(importlib.import_module(module), name)(settings, cloud)
    with (
        postgres_pool_scope(settings.database_url),
        httpx.Client(timeout=httpx.Timeout(60, connect=10), trust_env=False) as client,
    ):
        service = build_worker_loop_service(
            database_path=Path(settings.database_url),
            settings=settings,
            cloud_worker_composition=bundle,
            cloud_composition=cloud,
            model_http_client=client,
        )._execution_service
        if check:
            print(
                json.dumps(
                    {
                        "cloud_composition_ready": True,
                        "run_executed": False,
                        "composition_ms": round((time.monotonic() - started) * 1000, 1),
                    }
                )
            )
            return
        lease = WorkerLease.model_validate(request["lease"])
        # Parent alone owns heartbeat/release; avoid checkpoint races between processes.
        claimed = ClaimedSession(
            lease=lease,
            recovery=service._recovery_service.recover_session(
                lease.session_id,
                worker_lease=lease,
            ),
        )

        def require_owned() -> None:
            current = service._claim_service._lease_store.get(lease.session_id)
            if current is None or current.fence != lease.fence:
                raise LeaseLostError("isolated executor fence revoked")

        try:
            result = execute_claimed_with_stale_retry(
                service,
                claimed,
                started_at=datetime.fromisoformat(request["executed_at"]),
                ownership_check=require_owned,
            )
        except WorkerInputPreparationUnavailable:
            # Only the shared pre-model preparation boundary emits this type.
            # No exception message, credentials or execution input crosses IPC.
            write_input_failure(result_path, request)
            return
        result_path.write_bytes(TypeAdapter(ExecutedSession).dump_json(result))


if __name__ == "__main__":
    main()
