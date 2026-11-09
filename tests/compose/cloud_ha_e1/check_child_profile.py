"""Run real startup/exit hooks; wrong marker, scope and parent stay inactive."""

import os
import pstats
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

source = Path(__file__).with_name("child_profile_sitecustomize.py")
for marker, namespace, module, argument, expected in (
    ("1", "ha-e1-20261102", "zebra_agent_worker.session_process_child", "--execute", 1),
    ("0", "ha-e1-20261102", "zebra_agent_worker.session_process_child", "--execute", 0),
    ("1", "foreign", "zebra_agent_worker.session_process_child", "--execute", 0),
    ("1", "ha-e1-20261102", "parent_probe", "--execute", 0),
    ("1", "ha-e1-20261102", "zebra_agent_worker.session_process_child", "--check", 0),
):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copyfile(source, root / "sitecustomize.py")
        package = root / "zebra_agent_worker"
        package.mkdir()
        (package / "__init__.py").touch()
        script = """def profile_check():
    return sum(range(1000))
assert profile_check() == 499500
"""
        (package / "session_process_child.py").write_text(script)
        (root / "parent_probe.py").write_text(script)
        environment = {
            **os.environ,
            "PYTHONPATH": directory,
            "TMPDIR": directory,
            "ZEBRA_HA_E1_CHILD_PROFILE": marker,
            "ZEBRA_DEPLOYMENT_NAMESPACE": namespace,
        }
        subprocess.run(
            [sys.executable, "-m", module, argument, "zebra_agent_worker.session_process_child"],
            cwd=directory,
            env=environment,
            capture_output=True,
            check=True,
            timeout=10,
        )
        files = list(root.glob("zebra-ha-e1-child-*.pstats"))
        assert len(files) == expected
        if files:
            assert files[0].stat().st_mode & 0o777 == 0o600
            assert any(name == "profile_check" for _, _, name in pstats.Stats(str(files[0])).stats)
print("Real child profile recorded; disabled marker, foreign scope and parent produced no profile.")
