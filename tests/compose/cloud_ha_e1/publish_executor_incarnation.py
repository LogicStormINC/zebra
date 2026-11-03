"""Publish an E1 Worker identity from the trusted Docker host."""

import argparse
import fcntl
import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True, timeout=5).strip()


def identity(container: str) -> dict[str, str]:
    engine = docker("info", "--format", "{{.ID}}")
    spec = json.loads(docker("inspect", "--type", "container", container))[0]
    state = spec["State"]
    if (
        not engine
        or spec["Config"]["Labels"].get("zebra.ha.owner") != "ca-ha-03-e1-20261102"
        or spec["HostConfig"]["PidMode"] != ""
        or spec["HostConfig"]["Privileged"]
        or not state["Running"]
        or state["Pid"] <= 0
    ):
        raise ValueError("expected a running, owned E1 Worker with a private PID namespace")
    namespace = os.readlink(f"/proc/{state['Pid']}/ns/pid")
    current = json.loads(docker("inspect", "--type", "container", spec["Id"]))[0]["State"]
    if not current["Running"] or any(current[key] != state[key] for key in ("Pid", "StartedAt")):
        raise ValueError("Worker incarnation changed during identity capture")
    return {
        "engine": engine,
        "container": spec["Id"],
        "started_at": state["StartedAt"],
        "pid_namespace": namespace,
    }


def exit_witness(container: str, binding_path: Path) -> dict[str, str]:
    binding = json.loads(binding_path.read_bytes())
    spec = json.loads(docker("inspect", "--type", "container", container))[0]
    state = spec["State"]
    if (
        binding["engine"] != docker("info", "--format", "{{.ID}}")
        or spec["Id"] != binding["container"]
        or state["StartedAt"] != binding["started_at"]
        or spec["Config"]["Labels"].get("zebra.ha.owner") != "ca-ha-03-e1-20261102"
        or spec["HostConfig"]["PidMode"] != ""
        or spec["HostConfig"]["Privileged"]
        or state["Status"] != "exited"
        or state["Running"]
        or state["Pid"] != 0
        or datetime.fromisoformat(state["FinishedAt"])
        <= datetime.fromisoformat(binding["started_at"])
    ):
        raise ValueError("no exit proof for the registered E1 Worker incarnation")
    return {**binding, "finished_at": state["FinishedAt"]}


def publish(binding: dict[str, str], destination: Path) -> None:
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        temporary = Path(directory) / "identity.json"
        with temporary.open("x") as file:
            json.dump(binding, file)
            file.flush()
            os.fchmod(file.fileno(), 0o444)
            os.fsync(file.fileno())
        temporary.replace(destination)
        fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def acknowledge_exit(
    witness: dict[str, str], session: UUID, fence_json: str, dsn: str, *, namespace: str
) -> None:
    # Imports stay optional for a host that only publishes identity files.
    from agent_core.domain.leases import LeaseFence
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.force_stop_executors import acknowledge_executor_incarnation

    fields = ("engine", "container", "started_at", "pid_namespace")
    incarnation = {key: witness[key] for key in fields}
    if not acknowledge_executor_incarnation(
        PostgresDatabase(dsn, deployment_namespace=namespace),
        session,
        LeaseFence.model_validate_json(fence_json),
        incarnation=incarnation,
    ):
        raise ValueError("exit witness does not match an executor registration")


def reconcile_exits(witness: dict[str, str], dsn: str, *, namespace: str) -> int:
    from agent_storage.postgres.connection_capacity import connect

    fields = ("engine", "container", "started_at", "pid_namespace")
    incarnation = {key: witness[key] for key in fields}
    with connect(dsn, lane="control", connect_timeout=2) as connection:
        connection.execute("SET LOCAL statement_timeout='1500ms'")
        rows = connection.execute(
            """SELECT s.response_body
            FROM control_plane_idempotency_records i
            JOIN control_plane_idempotency_records s
              ON s.deployment_namespace=i.deployment_namespace
             AND s.idempotency_key=i.idempotency_key AND s.action='executor_started'
            LEFT JOIN control_plane_idempotency_records e
              ON e.deployment_namespace=i.deployment_namespace
             AND e.idempotency_key=i.idempotency_key AND e.action='executor_exit'
            WHERE i.deployment_namespace=%s AND i.action='executor_incarnation'
              AND i.response_body=%s::jsonb AND e.response_body IS DISTINCT FROM s.response_body
            ORDER BY i.idempotency_key LIMIT 100""",
            (namespace, json.dumps(incarnation)),
        ).fetchall()
    for (start,) in rows:
        acknowledge_exit(
            witness, UUID(start["session_id"]), json.dumps(start["fence"]), dsn, namespace=namespace
        )
    return len(rows)


def reconcile_in_cleanup(container: str, witness: dict[str, str], *, namespace: str) -> int:
    spec = json.loads(docker("inspect", "--type", "container", container))[0]
    if (
        not spec["State"]["Running"]
        or spec["Config"]["Labels"].get("zebra.ha.owner") != "ca-ha-03-e1-20261102"
        or spec["Name"] != "/zebra-ha-e1-20261102-runtime-cleanup-1-corpus"
        or f"ZEBRA_DEPLOYMENT_NAMESPACE={namespace}" not in spec["Config"]["Env"]
    ):
        raise ValueError("expected the owned E1 cleanup container")
    root = Path(__file__).resolve().parents[3]
    storage = root / "packages/agent-storage/src/agent_storage/postgres/force_stop_executors.py"
    child = (
        "import os\n"
        "from agent_storage.postgres import force_stop_executors as storage\n"
        f"exec(compile({storage.read_bytes()!r}, 'executor_storage', 'exec'), vars(storage))\n"
        + Path(__file__).read_text().rsplit('if __name__ == "__main__":', 1)[0]
        + "\nfrom agent_storage.postgres.connection_capacity import (\n"
        + "    PROFILE_ENV, ConnectionBudget, capacity_scope,\n"
        + ")\n"
        + "from agent_storage.postgres.capacity_profile import CapacityProfile\n"
        + "dsn = os.environ['ZEBRA_DATABASE_URL']\n"
        + "profile = CapacityProfile.parse(os.environ[PROFILE_ENV])\n"
        + "budget = ConnectionBudget(dsn, profile, 'cleanup')\n"
        + "with capacity_scope(budget):\n"
        + f"    count = reconcile_exits({witness!r}, dsn, namespace={namespace!r})\n"
        + "assert budget.stats()['peak']['control'] == 1\n"
        + "assert not any(budget.stats()['active'].values())\n"
        + "print(count)\n"
    )
    result = subprocess.check_output(
        ["docker", "exec", "-i", spec["Id"], "python", "-"],
        input=child, text=True, timeout=15,
    )
    return int(result.strip())


def restart_reconciled(
    container: str, binding_path: Path, destination: Path, dsn: str, *, namespace: str,
    reconcile: Callable[[dict[str, str]], int] | None = None,
    abnormal_only: bool = False,
) -> int:
    binding_path = binding_path.resolve()
    lock_path = binding_path.with_suffix(".restart.lock")
    if destination.resolve() in {binding_path, lock_path}:
        raise ValueError("exit witness must have a separate destination")
    with lock_path.open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        spec = json.loads(docker("inspect", "--type", "container", container))[0]
        state = spec["State"]
        running = state["Status"] == "running"
        if abnormal_only and not running and (
            state["Status"] != "exited" or state["ExitCode"] in {0, 143}
        ):
            return 0
        if running:
            previous = json.loads(binding_path.read_bytes())
            if abnormal_only and (
                spec["Id"] == previous["container"]
                and state["StartedAt"] == previous["started_at"]
            ):
                # No mutation on a healthy tick. An exit after this snapshot is
                # handled by the next tick instead of a second identity read.
                return 0
            current = identity(container)
            if current == previous:
                return 0
            witness = json.loads(destination.read_bytes())
            original = {key: value for key, value in witness.items() if key != "finished_at"}
            if (
                original != previous
                or any(current[key] != previous[key] for key in ("engine", "container"))
                or not datetime.fromisoformat(previous["started_at"])
                < datetime.fromisoformat(witness["finished_at"])
                <= datetime.fromisoformat(current["started_at"])
            ):
                raise ValueError("saved exit witness does not match the restarted Worker")
        else:
            witness = exit_witness(container, binding_path)
            publish(witness, destination)
        if reconcile is None:
            count = reconcile_exits(witness, dsn, namespace=namespace)
            remaining = reconcile_exits(witness, dsn, namespace=namespace)
        else:
            count = reconcile(witness)
            remaining = reconcile(witness)
        if remaining:
            raise RuntimeError("executor exits are still being reconciled; retry before restarting")
        container = witness["container"]
        if not running:
            if exit_witness(container, binding_path) != witness:
                raise ValueError("Worker exit witness changed before restart")
            docker("start", container)
            current = identity(container)
        elif identity(container) != current:
            raise ValueError("Worker changed during restart recovery")
        publish(current, binding_path)
        return count


def recover_crash(
    container: str, binding_path: Path, destination: Path, dsn: str, *, namespace: str,
    reconcile: Callable[[dict[str, str]], int] | None = None,
) -> int:
    """One periodic recovery tick for a single explicitly managed E1 Worker."""
    spec = json.loads(docker("inspect", "--type", "container", container))[0]
    state = spec["State"]
    if state["Status"] == "running" or (
        state["Status"] == "exited" and state["ExitCode"] not in {0, 143}
    ):
        return restart_reconciled(
            spec["Id"], binding_path, destination, dsn, namespace=namespace,
            reconcile=reconcile, abnormal_only=True,
        )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--exit-binding", type=Path)
    parser.add_argument("--ack-session", type=UUID)
    parser.add_argument("--ack-fence")
    parser.add_argument("--reconcile", action="store_true")
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--recover-crash", action="store_true")
    parser.add_argument("--cleanup-container")
    parser.add_argument("--namespace", default="ha-e1-20261102")
    arguments = parser.parse_args()
    reconcile = None
    if arguments.cleanup_container:
        def reconcile(witness: dict[str, str]) -> int:
            return reconcile_in_cleanup(
                arguments.cleanup_container, witness, namespace=arguments.namespace
            )

    if arguments.recover_crash:
        if (
            arguments.exit_binding is None
            or arguments.reconcile
            or arguments.restart
            or arguments.ack_session
            or arguments.ack_fence
        ):
            parser.error("--recover-crash requires --exit-binding and no other recovery mode")
        count = recover_crash(
            arguments.container, arguments.exit_binding, arguments.destination,
            os.environ.get("ZEBRA_DATABASE_URL", ""), namespace=arguments.namespace,
            reconcile=reconcile,
        )
        if count:
            print(count)
        raise SystemExit(0)
    if arguments.restart and not arguments.reconcile:
        parser.error("--restart requires --reconcile")
    if arguments.reconcile and (arguments.exit_binding is None or arguments.ack_session):
        parser.error("--reconcile requires --exit-binding without --ack-session")
    if bool(arguments.ack_session) != bool(arguments.ack_fence) or (
        arguments.ack_session and arguments.exit_binding is None
    ):
        parser.error("acknowledgment requires --exit-binding, --ack-session and --ack-fence")
    if arguments.restart:
        if arguments.exit_binding.resolve() == arguments.destination.resolve():
            parser.error("exit witness must have a separate destination")
        print(restart_reconciled(
            arguments.container, arguments.exit_binding, arguments.destination,
            os.environ.get("ZEBRA_DATABASE_URL", ""), namespace=arguments.namespace,
            reconcile=reconcile,
        ))
        raise SystemExit(0)
    if arguments.exit_binding is None:
        binding = identity(arguments.container)
    else:
        if arguments.exit_binding.resolve() == arguments.destination.resolve():
            parser.error("exit witness must have a separate destination")
        binding = exit_witness(arguments.container, arguments.exit_binding)
    publish(binding, arguments.destination)
    if arguments.ack_session:
        acknowledge_exit(
            binding, arguments.ack_session, arguments.ack_fence,
            os.environ["ZEBRA_DATABASE_URL"], namespace=arguments.namespace,
        )
    if arguments.reconcile:
        dsn = os.environ["ZEBRA_DATABASE_URL"]
        print(reconcile_exits(binding, dsn, namespace=arguments.namespace))
