"""Serial runner guards; these cases do not count as native grid acceptance."""

import asyncio
import json

import joint_concurrency_runner as runner
from support import E2EError


def test_grid_history_major_and_no_silent_failed_cell(tmp_path, monkeypatch):
    calls = []

    async def case(config, conversation, *, history, observers):
        calls.append((history, observers))
        if len(calls) == 5:
            raise ExceptionGroup("private DSN must never be exported", [E2EError("native_failed")])
        return {"scope": "guard_only"}

    monkeypatch.setattr(runner, "run_concurrency_case", case)
    output = tmp_path / "grid"
    summary = asyncio.run(runner.run_serial(None, "conversation", output, pilot=False))
    assert calls == [(1000, 1), (1000, 10), (1000, 50), (1000, 100), (10000, 1)]
    assert summary["status"] == "blocked" and summary["expected_cells"] == 12
    assert summary["cells"][-1]["reasons"] == ["native_failed"]
    assert "private DSN" not in (output / "summary.json").read_text()
    assert json.loads((output / "summary.json").read_text()) == summary


def test_pilot_does_not_start_remaining_grid(tmp_path, monkeypatch):
    calls = []

    async def case(config, conversation, *, history, observers):
        calls.append((history, observers))
        return {"scope": "guard_only"}

    monkeypatch.setattr(runner, "run_concurrency_case", case)
    summary = asyncio.run(runner.run_serial(None, "conversation", tmp_path / "pilot", pilot=True))
    assert calls == [(1000, 1)] and summary["status"] == "passed"
    assert summary["full_goal_passed"] is False


def test_private_inputs_permissions_checked_before_loading_secrets(tmp_path):
    path = tmp_path / "inputs.json"
    path.write_text("private-invalid-json")
    path.chmod(0o644)
    try:
        runner.load_private_config(path)
    except ValueError as exc:
        assert str(exc) == "private_bounded_inputs_required"
    else:
        raise AssertionError("public inputs accepted")
