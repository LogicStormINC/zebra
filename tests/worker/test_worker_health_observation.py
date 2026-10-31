"""Local health is observation, not a lease, task result or termination receipt."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from zebra_agent_worker.loop import build_worker_loop_service
from zebra_agent_worker.worker_health import WorkerHealth, read_worker_health

from tests.worker.test_loop import _settings


def test_command_health_requires_current_own_capability_and_work_progress():
    now = [10.0]
    health = WorkerHealth(clock=lambda: now[0])
    lease = SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=30))
    assert not health.snapshot()["ready"]
    health.command_tick(lease, 10)
    assert health.snapshot()["ready"]
    before = health.snapshot()
    assert health.snapshot() == before  # Reads never advance progress.
    now[0] = 16
    assert not health.snapshot()["ready"]
    health.command_tick(lease, 10)
    assert not health.snapshot()["ready"]
    health.command_tick(None, 16)
    assert not health.snapshot()["ready"]
    health.command_tick(SimpleNamespace(expires_at=datetime.now(UTC) - timedelta(seconds=1)), 16)
    assert not health.snapshot()["ready"]
    health.command_tick(lease, 16)
    assert health.snapshot()["ready"]
    health.close()
    health.command_tick(lease, 16)
    assert not health.snapshot()["ready"]


def test_long_legacy_execution_is_unknown_not_a_failed_task():
    now = [10.0]
    health = WorkerHealth(clock=lambda: now[0])
    health.legacy_tick(busy=False)
    assert health.snapshot()["ready"]
    health.legacy_tick(busy=True)
    now[0] += 600
    state = health.snapshot()
    assert state["phase"] == "legacy_busy"
    assert not state["ready"]
    assert "task_status" not in state and "resources_released" not in state
    health.legacy_tick(busy=False)
    assert health.snapshot()["ready"]


def test_atomic_private_snapshot_rejects_stale_or_other_process(tmp_path):
    now = [10.0]
    path = tmp_path / "health.json"
    health = WorkerHealth(clock=lambda: now[0])
    health.attach(path)
    assert path.stat().st_mode & 0o777 == 0o600
    health.legacy_tick(busy=False)
    state = health.snapshot()
    assert read_worker_health(path, state["pid"], state["instance_id"], now=10)["ready"]
    assert not read_worker_health(path, state["pid"] + 1, state["instance_id"], now=10)["ready"]
    assert not read_worker_health(path, state["pid"], "another-instance", now=10)["ready"]
    assert not read_worker_health(path, state["pid"], state["instance_id"], now=16)["ready"]
    assert json.loads(path.read_text()) == state
    health.close()
    assert not json.loads(path.read_text())["ready"]
    assert list(tmp_path.iterdir()) == [path]


def test_actual_legacy_loop_updates_then_closes_observation(tmp_path):
    service = build_worker_loop_service(
        database_path=tmp_path / "worker.sqlite",
        settings=_settings(tmp_path / "worker.sqlite"),
        sleep=lambda _: None,
    )
    seen = []
    original = service.poll_once

    def poll(**kwargs):
        seen.append(service.health.snapshot())
        return original(**kwargs)

    service.poll_once = poll
    result = service.run(worker_id="ha-test", max_cycles=1, stop_when_idle=True)
    assert result.idle_cycles == 1
    assert seen[0]["phase"] == "legacy_busy" and not seen[0]["ready"]
    assert service.health.snapshot()["phase"] == "stopped"


def test_malformed_snapshot_and_closed_state_are_not_current(tmp_path):
    path = tmp_path / "state.json"
    for raw in ["[]", "{", '"text"', " " * 4097, '{"ready":true}']:
        path.write_text(raw)
        assert not read_worker_health(path, 1, "expected", now=10)["ready"]
    health = WorkerHealth()
    health.legacy_tick(busy=False)
    health.close()
    assert not health.snapshot()["control_fresh"]


def test_cli_opt_in_file_is_closed_after_actual_local_loop(tmp_path, monkeypatch):
    import importlib

    module = importlib.import_module("zebra_agent_worker.main")
    monkeypatch.setattr(module, "load_settings", lambda: _settings(tmp_path / "cli.sqlite"))
    path = tmp_path / "cli-health.json"
    assert module.main(["--max-cycles", "1", "--stop-when-idle", "--health-file", str(path)]) == 0
    assert json.loads(path.read_text())["phase"] == "stopped"
    assert path.stat().st_mode & 0o777 == 0o600


def test_capability_expiry_wins_over_fresh_control_sample(tmp_path):
    now = [10.0]
    path = tmp_path / "expiry.json"
    health = WorkerHealth(clock=lambda: now[0])
    health.attach(path)
    lease = SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=2))
    health.command_tick(lease, 10)
    state = health.snapshot()
    assert state["ready"]
    now[0] += 3  # Observation is fresh, but its capability can no longer support readiness.
    assert health.snapshot()["control_fresh"]
    assert not health.snapshot()["ready"]
    assert not read_worker_health(path, state["pid"], state["instance_id"], now=now[0])["ready"]


def test_snapshot_write_failure_cannot_fail_task_control(tmp_path, monkeypatch):
    import zebra_agent_worker.worker_health as module

    health = WorkerHealth()
    health.attach(tmp_path / "owned.json")

    def unavailable(*args):
        raise OSError("owned filesystem unavailable")

    monkeypatch.setattr(module.os, "replace", unavailable)
    health.legacy_tick(busy=False)
    assert not health.snapshot()["ready"]
    health.close()
    assert list(tmp_path.iterdir()) == [tmp_path / "owned.json"]


def test_attach_never_overwrites_existing_data_or_another_instance(tmp_path):
    import pytest

    path = tmp_path / "existing.sqlite"
    original = b"retained historical database bytes"
    path.write_bytes(original)
    with pytest.raises(FileExistsError):
        WorkerHealth().attach(path)
    assert path.read_bytes() == original
    owned = tmp_path / "owned.json"
    first = WorkerHealth()
    first.attach(owned)
    first.legacy_tick(busy=False)
    before = owned.read_bytes()
    with pytest.raises(FileExistsError):
        WorkerHealth().attach(owned)
    assert owned.read_bytes() == before
    first.close()
    stopped = owned.read_bytes()
    first.close()
    assert owned.read_bytes() == stopped


def test_cached_readiness_cannot_outlive_real_control_progress(tmp_path):
    now = [14.5]
    path = tmp_path / "control-age.json"
    health = WorkerHealth(clock=lambda: now[0])
    health.attach(path)
    lease = SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=30))
    health.command_tick(lease, 10.0)  # The last real completed control/maintenance is 4.5s old.
    state = health.snapshot()
    assert state["ready"]
    now[0] = 15.1  # Cache is fresh, but actual progress is older than the five-second budget.
    assert not health.snapshot()["ready"]
    assert not health.snapshot()["control_fresh"]
    assert not read_worker_health(path, state["pid"], state["instance_id"], now=now[0])["ready"]


def test_local_reader_rejects_symbolic_link(tmp_path):
    health = WorkerHealth()
    source = tmp_path / "source.json"
    alias = tmp_path / "alias.json"
    health.attach(source)
    health.legacy_tick(busy=False)
    state = health.snapshot()
    alias.symlink_to(source)
    assert not read_worker_health(
        alias, state["pid"], state["instance_id"], now=state["observed_at"]
    )["ready"]


def test_local_reader_rejects_fifo_without_blocking(tmp_path):
    import os
    import subprocess
    import sys

    path = tmp_path / "not-a-snapshot"
    os.mkfifo(path)
    code = (
        "from pathlib import Path; from time import monotonic; "
        "from zebra_agent_worker.worker_health import read_worker_health; "
        "import sys; assert not read_worker_health(Path(sys.argv[1]), 1, 'expected', "
        "now=monotonic())['ready']"
    )
    # A reverted blocking FIFO open must fail and be reaped, never hang the test runner.
    try:
        subprocess.run([sys.executable, "-c", code, str(path)], check=True, timeout=5)
    finally:
        path.unlink(missing_ok=True)


def test_recording_overhead_cannot_extend_progress_deadline():
    now = [14.0]

    def clock():
        now[0] += 0.1
        return now[0]

    health = WorkerHealth(clock=clock)
    lease = SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=30))
    health.command_tick(lease, 10.0)
    assert health.snapshot()["valid_until"] <= 15.0
