"""Cloud-only, operator-selected execution process; never kill a shared Worker."""

import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from time import monotonic_ns
from typing import Any

from agent_runtime import executor_supervisor
from agent_runtime.process_supervision import supervise_process
from agent_runtime.process_supervision import terminate_group as terminate_group
from pydantic import TypeAdapter

from zebra_agent_worker.execution_errors import WorkerExecutorInterrupted
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.execution_finalization import ExecutedSession

logger = logging.getLogger(__name__)


def process_factory(settings: Any) -> str | None:
    factory = os.environ.get("ZEBRA_SESSION_PROCESS_FACTORY")
    if not factory or os.environ.get("ZEBRA_SESSION_PROCESS_CHILD") == "1":
        return None
    if settings.storage_authority != "postgresql" or settings.deployment != "cloud":
        raise ValueError("session process isolation requires Cloud PostgreSQL composition")
    if not hasattr(os, "waitid"):
        raise ValueError("Cloud executor isolation requires Linux waitid ownership fencing")
    return factory


def executor_incarnation() -> dict[str, str] | None:
    """Read the trusted node's per-start identity from an operator-mounted file."""
    path = os.environ.get("ZEBRA_EXECUTOR_INCARNATION_FILE")
    if path is None:
        return None
    try:
        identity = json.loads(Path(path).read_bytes())
        if (
            not isinstance(identity, dict)
            or identity.keys() != {"engine", "container", "started_at", "pid_namespace"}
            or not all(isinstance(value, str) and value.strip() for value in identity.values())
            or identity["pid_namespace"] != os.readlink("/proc/self/ns/pid")
        ):
            raise ValueError("executor incarnation does not match this PID namespace")
        return identity
    except (OSError, ValueError) as error:
        raise WorkerExecutorInterrupted("trusted executor incarnation unavailable") from error


def settings_digest(settings: Any) -> str:
    raw = json.dumps(asdict(settings), sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def supervise(
    process: subprocess.Popen[Any], cancelled: Any, *, interval: float = 0.5, on_exit: Any = None
) -> None:
    if supervise_process(process, cancelled, interval=interval, on_exit=on_exit):
        raise ExecutionInterrupted("session cancelled; isolated executor stopped")


def execute_isolated(service: Any, request: dict[str, Any]) -> ExecutedSession:
    factory = process_factory(service._settings)
    assert factory is not None
    from uuid import UUID

    from agent_core.domain.identifiers import SessionId

    sid = SessionId(UUID(request["session_id"]))
    from agent_core.domain.leases import WorkerLease
    from agent_storage.postgres.force_stop_executors import executor_monitor, register_executor
    from agent_storage.postgres.force_stops import PostgresForceStops

    lease = WorkerLease.model_validate(request["lease"])
    database = service._projection_store._database
    store = PostgresForceStops(database._dsn, deployment_namespace=database.deployment_namespace)
    request.update(
        factory=factory,
        settings_digest=settings_digest(service._settings),
        parent_pid=os.getpid(),
        deployment_namespace=database.deployment_namespace,
    )
    # ponytail: one process per execution preserves exact cancellation ownership;
    # reusable executors need a proven job/ack boundary; measure startup before rollout.
    with tempfile.TemporaryDirectory(prefix="zebra-session-") as temporary:
        root = Path(temporary)
        source, result = root / "request.json", root / "result.json"
        request["executor_command"] = [
            sys.executable,
            str(Path(__file__).with_name("session_process_child.py")),
            "--execute",
            str(source),
            str(result),
        ]
        request["exit_receipt"] = {
            "session_id": str(sid),
            "fence": lease.fence.model_dump(mode="json"),
        }
        source.write_text(json.dumps(request))
        registration_started = monotonic_ns()
        register_executor(store.database, sid, lease.fence, incarnation=executor_incarnation())
        launch_started = monotonic_ns()
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(executor_supervisor.__file__)),
                    str(source),
                    str(result),
                ],
                start_new_session=True,
                env={
                    **os.environ,
                    "ZEBRA_SESSION_PROCESS_CHILD": "1",
                    "ZEBRA_SESSION_PROCESS_LAUNCH_NS": str(launch_started),
                    "PYTHONPATH": os.pathsep.join(sys.path),
                },
            )
        except OSError as error:
            store.acknowledge_executor(sid, lease.fence)
            raise WorkerExecutorInterrupted("isolated executor launch failed") from error

        logger.info(
            "worker_executor_launched session_id=%s fence=%s registration_ms=%s spawn_ms=%s",
            sid, lease.fence.fencing_token,
            (launch_started - registration_started) // 1_000_000,
            (monotonic_ns() - launch_started) // 1_000_000,
        )

        def acknowledge() -> None:
            receipt = json.loads(result.with_suffix(".exit.json").read_text())
            if receipt != {"session_id": str(sid), "fence": lease.fence.model_dump(mode="json")}:
                raise WorkerExecutorInterrupted("executor exit proof conflicts")
            store.acknowledge_executor(sid, lease.fence)

        with executor_monitor(database, sid) as cancelled:
            supervise(process, cancelled, on_exit=acknowledge)
        result_present = result.exists()
        if process.returncode != 0 or not result_present:
            logger.warning(
                "worker_executor_outcome_unknown session_id=%s fence=%s returncode=%s "
                "result_present=%s",
                sid, lease.fence.fencing_token, process.returncode, result_present,
            )
            raise WorkerExecutorInterrupted("isolated executor outcome unknown")
        try:
            return TypeAdapter(ExecutedSession).validate_json(result.read_bytes())
        except (ValueError, OSError) as error:
            raise WorkerExecutorInterrupted("isolated executor receipt unavailable") from error
