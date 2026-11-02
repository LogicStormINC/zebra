"""Cloud-only, operator-selected execution process; never kill a shared Worker."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent_runtime import executor_supervisor
from agent_runtime.process_supervision import supervise_process
from agent_runtime.process_supervision import terminate_group as terminate_group
from pydantic import TypeAdapter

from zebra_agent_worker.execution_errors import (
    WorkerExecutorInterrupted,
    WorkerInputPreparationUnavailable,
)
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.execution_finalization import ExecutedSession


def process_factory(settings: Any) -> str | None:
    factory = os.environ.get("ZEBRA_SESSION_PROCESS_FACTORY")
    if not factory or os.environ.get("ZEBRA_SESSION_PROCESS_CHILD") == "1":
        return None
    if settings.storage_authority != "postgresql" or settings.deployment != "cloud":
        raise ValueError("session process isolation requires Cloud PostgreSQL composition")
    if not hasattr(os, "waitid"):
        raise ValueError("Cloud executor isolation requires Linux waitid ownership fencing")
    return factory


def settings_digest(settings: Any) -> str:
    raw = json.dumps(asdict(settings), sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def supervise(
    process: subprocess.Popen[Any], cancelled: Any, *, interval: float = 0.5, on_exit: Any = None
) -> None:
    if supervise_process(process, cancelled, interval=interval, on_exit=on_exit):
        raise ExecutionInterrupted("session cancelled; isolated executor stopped")


def input_failure_receipt(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "kind": "execution_input_unavailable",
        "session_id": request["session_id"],
        "fence": request["lease"]["fence"],
    }


def write_input_failure(result: Path, request: dict[str, Any]) -> None:
    temporary = result.with_suffix(".error.tmp")
    temporary.write_text(json.dumps(input_failure_receipt(request)))
    temporary.replace(result.with_suffix(".error.json"))


def require_input_failure(result: Path, request: dict[str, Any]) -> None:
    receipt = result.with_suffix(".error.json")
    if not receipt.exists():
        return
    try:
        if receipt.is_symlink() or receipt.stat().st_size > 2048:
            raise ValueError("invalid failure receipt")
        with receipt.open("rb") as stream:
            raw = stream.read(2049)
        if len(raw) > 2048:
            raise ValueError("oversize failure receipt")
        value = json.loads(raw)
        if (
            json.dumps(value, sort_keys=True)
            != json.dumps(input_failure_receipt(request), sort_keys=True)
            or result.exists()
        ):
            raise ValueError("failure receipt conflicts")
    except (ValueError, OSError) as error:
        raise WorkerExecutorInterrupted("executor failure proof unavailable") from error
    raise WorkerInputPreparationUnavailable("execution_input_unavailable")


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
            "-m",
            "zebra_agent_worker.session_process_child",
            "--execute",
            str(source),
            str(result),
        ]
        request["exit_receipt"] = {
            "session_id": str(sid),
            "fence": lease.fence.model_dump(mode="json"),
        }
        source.write_text(json.dumps(request))
        register_executor(store.database, sid, lease.fence)
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
                    "PYTHONPATH": os.pathsep.join(sys.path),
                },
            )
        except OSError as error:
            store.acknowledge_executor(sid, lease.fence)
            raise WorkerExecutorInterrupted("isolated executor launch failed") from error

        def acknowledge() -> None:
            receipt = json.loads(result.with_suffix(".exit.json").read_text())
            if receipt != {"session_id": str(sid), "fence": lease.fence.model_dump(mode="json")}:
                raise WorkerExecutorInterrupted("executor exit proof conflicts")
            store.acknowledge_executor(sid, lease.fence)

        with executor_monitor(database, sid) as cancelled:
            supervise(process, cancelled, on_exit=acknowledge)
        if process.returncode == 0:
            require_input_failure(result, request)
        if process.returncode != 0 or not result.exists():
            raise WorkerExecutorInterrupted("isolated executor outcome unknown")
        try:
            return TypeAdapter(ExecutedSession).validate_json(result.read_bytes())
        except (ValueError, OSError) as error:
            raise WorkerExecutorInterrupted("isolated executor receipt unavailable") from error
