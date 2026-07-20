import subprocess
import sys


def test_eval_release_check_passes_baseline_dataset() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/eval_release_check.py"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "eval release gate: passed=True" in result.stdout
    assert "cases=10" in result.stdout
