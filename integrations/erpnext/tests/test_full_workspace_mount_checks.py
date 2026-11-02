"""python3 tests/test_full_workspace_mount_checks.py [operator-installer.py]."""

import ast
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

source = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path(__file__).resolve().parents[1] / "deploy/activate_full_capability_operator.py"
)
program = next(
    ast.literal_eval(node.value)
    for node in ast.walk(ast.parse(source.read_text()))
    if isinstance(node, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id == "prepare" for t in node.targets)
)


def prepare(existing):
    commands = []

    def run(argv, **kwargs):
        commands.append(argv)
        return SimpleNamespace(returncode=0 if existing or argv[0] != "findmnt" else 1)

    # A bind on the parent's filesystem deliberately returns False here.
    # The native mount table, rather than st_dev, must decide whether to bind.
    with (
        patch.object(Path, "is_symlink", return_value=False),
        patch.object(Path, "is_dir", return_value=True),
        patch.object(Path, "is_mount", return_value=False),
        patch.object(Path, "stat", return_value=SimpleNamespace(st_uid=0, st_mode=0o40755)),
        patch.object(Path, "mkdir"),
        patch("os.chown"),
        patch("os.chmod"),
        patch.object(subprocess, "run", side_effect=run),
    ):
        exec(compile(program, str(source), "exec"), {})
    return commands


for _ in range(2):
    assert not any(c[0] == "mount" for c in prepare(True)), (
        "existing bind must not be stacked or re-propagated"
    )
commands = prepare(False)
assert len([c for c in commands if c[:2] == ["mount", "--bind"]]) == 2
assert len([c for c in commands if c[:2] == ["mount", "--make-shared"]]) == 1
assert any(c[0] == "install" for c in commands), "existing credential setup preserved"
print("PASS same-filesystem bind detection, repeated preparation and first setup; no real mounts")
