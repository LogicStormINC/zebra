"""Regression for owned-container teardown; live checks never prune shared Docker state."""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(os.environ.get("ZEBRA_TEST_FIXTURE_SOURCE_ROOT", Path(__file__).resolve().parents[1]))
SOURCES = (
    "tests/agent_storage/test_host_management.py",
    "tests/agent_storage/test_host_connector_management.py",
    "tests/agent_storage/test_bundle_definition_postgres.py",
    "tests/api/test_host_registry_management.py",
    "tests/api/test_host_connector_management.py",
    "tests/conformance/client_v1/run-real-process.sh",
)


def _commands() -> list[tuple[str, list[str]]]:
    commands = []
    for relative in SOURCES:
        path = ROOT / relative
        if not path.exists():
            # ponytail: newer branches retired these fixtures; legacy roots still check them.
            continue
        if path.suffix == ".sh":
            for line in path.read_text().splitlines():
                if line.strip().startswith("docker rm "):
                    commands.append((relative, shlex.split(line.split(">", 1)[0])))
            continue
        tree = ast.parse(path.read_text())
        for block in ast.walk(tree):
            if not isinstance(block, ast.Try):
                continue
            for statement in block.finalbody:
                for call in ast.walk(statement):
                    if not isinstance(call, ast.Call) or not call.args:
                        continue
                    argv = call.args[0]
                    if not isinstance(argv, ast.List):
                        continue
                    if [getattr(item, "value", None) for item in argv.elts[:2]] != ["docker", "rm"]:
                        continue
                    values = [
                        item.value if isinstance(item, ast.Constant) else f"${item.id}"
                        for item in argv.elts
                    ]
                    if values[:2] == ["docker", "rm"]:
                        commands.append((relative, values))
    assert commands, "No disposable-container teardown was checked"
    for source, command in commands:
        targets = [item for item in command[2:] if not item.startswith("-")]
        assert targets and all(re.fullmatch(r"\$[A-Za-z_]\w*", item) for item in targets), (
            f"{source}: teardown target is not owned by the test"
        )
    return commands


COMMANDS = _commands()


@pytest.mark.parametrize(("source", "command"), COMMANDS)
def test_teardown_explicitly_removes_anonymous_volumes(source: str, command: list[str]) -> None:
    options = [item for item in command[2:] if item.startswith("-")]
    assert "--volumes" in options or any(
        "v" in item[1:] for item in options if not item.startswith("--")
    ), f"{source}: container teardown leaves anonymous volumes behind"


def _docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True).strip()


@pytest.mark.parametrize("target", ["production-postgres", "*", "$(docker ps -aq)"])
def test_rejects_unowned_teardown_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    (tmp_path / "cleanup.sh").write_text(f"docker rm -fv {shlex.quote(target)}\n")
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    monkeypatch.setitem(globals(), "SOURCES", ("cleanup.sh",))
    with pytest.raises(AssertionError, match="not owned"):
        _commands()


@pytest.mark.skipif(
    os.environ.get("ZEBRA_TEST_DOCKER_CLEANUP_LIVE") != "1", reason="explicit Docker opt-in"
)
@pytest.mark.parametrize(("source", "command"), COMMANDS)
@pytest.mark.parametrize("failed_test", [False, True])
def test_owned_teardown_preserves_named_volume(
    source: str, command: list[str], failed_test: bool
) -> None:
    """Exercise the actual teardown argv against new, uniquely owned containers only."""
    token = uuid4().hex
    named = f"zebra-cleanup-regression-{token}"
    owned: dict[str, str] = {}
    anonymous: set[str] = set()
    try:
        _docker("volume", "create", named)
        for variable in dict.fromkeys(item for item in command if item.startswith("$")):
            owned[variable] = f"{named}-{len(owned)}"
            container = _docker(
                "run",
                "--rm",
                "-d",
                "--name",
                owned[variable],
                "--pull=never",
                "--network",
                "none",
                "--mount",
                f"type=volume,source={named},target=/sentinel",
                "--entrypoint",
                "sleep",
                "postgres:17-alpine",
                "120",
            )
            owned[variable] = container
            mounts = json.loads(_docker("inspect", container))[0]["Mounts"]
            anonymous.update(
                m["Name"] for m in mounts if m["Type"] == "volume" and m["Name"] != named
            )
            _docker("exec", container, "sh", "-c", "printf retained > /sentinel/marker")
        assert owned and anonymous
        try:
            try:
                if failed_test:
                    raise RuntimeError("injected test failure")
            finally:
                _docker(*[owned.get(item, item) for item in command[1:]])
        except RuntimeError as exc:
            assert failed_test and str(exc) == "injected test failure"
        for container in owned.values():
            assert subprocess.run(["docker", "inspect", container], capture_output=True).returncode
        for volume in anonymous:
            assert subprocess.run(
                ["docker", "volume", "inspect", volume], capture_output=True
            ).returncode, f"{source}: leaked {volume}"
        assert (
            _docker(
                "run",
                "--rm",
                "--pull=never",
                "--network",
                "none",
                "--read-only",
                "--mount",
                f"type=volume,source={named},target=/sentinel,readonly",
                "--tmpfs",
                "/var/lib/postgresql/data",
                "--entrypoint",
                "cat",
                "postgres:17-alpine",
                "/sentinel/marker",
            )
            == "retained"
        )
    finally:
        for container in owned.values():
            subprocess.run(["docker", "rm", "-fv", container], capture_output=True)
        for volume in anonymous | {named}:
            subprocess.run(["docker", "volume", "rm", volume], capture_output=True)
