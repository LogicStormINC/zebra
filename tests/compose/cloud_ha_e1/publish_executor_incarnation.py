"""Publish an E1 Worker identity from the trusted Docker host."""

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--exit-binding", type=Path)
    arguments = parser.parse_args()
    if arguments.exit_binding is None:
        binding = identity(arguments.container)
    else:
        if arguments.exit_binding.resolve() == arguments.destination.resolve():
            parser.error("exit witness must have a separate destination")
        binding = exit_witness(arguments.container, arguments.exit_binding)
    publish(binding, arguments.destination)
