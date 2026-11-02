"""Long monitors must leave the existing control lane available for exact exit ACKs."""

import json
import os
import subprocess
import sys
from contextlib import ExitStack
from uuid import UUID

import pytest
from agent_storage.postgres.capacity_profile import CapacityProfile
from agent_storage.postgres.connection_capacity import ConnectionBudget
from agent_storage.postgres.force_stop_executors import (
    acknowledge_executor,
    executor_monitor,
    executors_exited,
    register_executor,
)

from tests.agent_storage.test_postgres_connection_capacity import profile_data
from tests.agent_storage.test_postgres_worker_budget import dsn as shared_dsn
from tests.agent_storage.test_postgres_worker_budget import setup as shared_setup
from tests.agent_storage.test_postgres_worker_budget import started

dsn, setup = shared_dsn, shared_setup


def composed(setup):
    _, binding, database = started(setup)
    values = profile_data()
    values["control"] = 1
    database._capacity = ConnectionBudget(
        database._dsn, CapacityProfile.parse(json.dumps(values)), "worker"
    )
    sid = UUID(binding.task_id)
    register_executor(database, sid, binding.fence)
    return database, sid, binding.fence


@pytest.mark.parametrize("count", [1, 2])
def test_monitors_leave_single_control_permit_for_ack(setup, count):
    database, sid, fence = composed(setup)
    with ExitStack() as stack:
        monitors = [stack.enter_context(executor_monitor(database, sid)) for _ in range(count)]
        assert all(not cancelled() for cancelled in monitors)
        acknowledge_executor(database, sid, fence)
        permit = database._capacity.acquire("control")
        try:
            assert database._capacity.stats()["active"]["normal"] == count
        finally:
            permit.release()
    assert sum(database._capacity.stats()["active"].values()) == 0
    with database.connect() as c:
        assert executors_exited(c, database.deployment_namespace, sid, None)


@pytest.mark.skipif(sys.platform != "linux", reason="real Linux subreaper ownership proof")
def test_nonzero_child_keeps_exact_kernel_exit_receipt_and_persists_ack(setup, tmp_path):
    from agent_runtime import executor_supervisor
    from agent_runtime.process_supervision import supervise_process

    database, sid, fence = composed(setup)
    source, result = tmp_path / "request.json", tmp_path / "result.json"
    expected = {"session_id": str(sid), "fence": fence.model_dump(mode="json")}
    source.write_text(json.dumps({
        "parent_pid": os.getpid(), "exit_receipt": expected,
        "executor_command": [sys.executable, "-c", "raise SystemExit(7)"],
    }))
    process = subprocess.Popen(
        [sys.executable, executor_supervisor.__file__, str(source), str(result)],
        start_new_session=True,
    )

    def acknowledge():
        assert json.loads(result.with_suffix(".exit.json").read_text()) == expected
        acknowledge_executor(database, sid, fence)

    try:
        with executor_monitor(database, sid) as cancelled:
            assert not cancelled()
            assert not supervise_process(process, cancelled, interval=.02, on_exit=acknowledge)
        assert process.returncode == 1
        assert json.loads(result.with_suffix(".exit.json").read_text()) == expected
        with database.connect() as c:
            assert executors_exited(c, database.deployment_namespace, sid, None)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)


def test_normal_saturation_refuses_monitor_without_claiming_exit_or_control(setup):
    from agent_storage.postgres.connection_capacity import DatabaseCapacityExceeded

    database, sid, fence = composed(setup)
    permits = [database._capacity.acquire("normal") for _ in range(2)]
    try:
        with executor_monitor(database, sid) as cancelled:
            with pytest.raises(DatabaseCapacityExceeded):
                cancelled()
        control = database._capacity.acquire("control")
        control.release()
    finally:
        for permit in permits:
            permit.release()
    assert sum(database._capacity.stats()["active"].values()) == 0
    with database.connect() as c:
        assert not executors_exited(c, database.deployment_namespace, sid, None)
