"""Cold DNS and failed maintenance must not trap the live projector in a spin."""

import time

import pytest
from agent_integrations.ag_ui.checkpoint_consumer import AgUiCheckpointConsumer
from agent_integrations.ag_ui.checkpoint_plan import AG_UI_CHECKPOINT_VERSION
from agent_storage import PostgresAgentTaskStore
from agent_storage.postgres.projection_work import PostgresTaskProjectionWorkStore
from agent_storage.postgres.task_io import TaskIoConnections, _remaining

from tests.agent_integrations.ag_ui_checkpoint_consumer_scratch import (
    _append,
    _command,
    _consumer,
    _native,
    _task,
)
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _postgres_fixture
from tests.agent_storage.test_session_task_binding_reads import NAMESPACE, admit

dsn = _dsn_fixture
postgres_dsn = _postgres_fixture


def test_repair_survives_cold_resolver_in_existing_bounded_io_budget(dsn, monkeypatch):
    session, _ = admit(dsn)
    tasks = PostgresAgentTaskStore(dsn, deployment_namespace=NAMESPACE)
    task = tasks.ensure_for_session(session)
    queue = PostgresTaskProjectionWorkStore(tasks._database, AG_UI_CHECKPOINT_VERSION)
    queue.enable_projection_work()
    resolve = TaskIoConnections._resolve

    def cold(connector, deadline):
        # Model the observed 0.46s container cold resolver, without any real DNS.
        time.sleep(0.12)
        _remaining(deadline)
        return resolve(connector, deadline)

    monkeypatch.setattr(TaskIoConnections, "_resolve", cold)
    consumer = AgUiCheckpointConsumer(tasks, queue, namespace=NAMESPACE)
    assert consumer._repair_task(task.task_id)


def test_repair_failure_waits_before_discovery_then_reaches_next_task(
    tmp_path, monkeypatch, caplog,
):
    tasks, events, queue = _native(tmp_path)
    bad, good = _task(tasks, ordinal=1), _task(tasks, ordinal=2)
    queue.disable_projection_work()
    for task in (bad, good):
        _command(events, task)
    queue.enable_projection_work()
    for task in (bad, good):
        _append(events, task, 1)
    consumer = _consumer(tasks, queue)
    clock = [100.0]
    monkeypatch.setattr("agent_integrations.ag_ui.checkpoint_consumer.monotonic", lambda: clock[0])
    original = tasks.backfill_event_positions
    failures = []

    def unavailable(task, **kwargs):
        if task == bad.task_id:
            failures.append(task)
            raise TimeoutError("resolver unavailable")
        return original(task, **kwargs)

    monkeypatch.setattr(tasks, "backfill_event_positions", unavailable)
    assert consumer.repair_once() == 0
    read = queue.read_projection_work_repairs

    def unexpected_discovery(**kwargs):
        pytest.fail("failed repair hot-polled SQL during cooldown")

    monkeypatch.setattr(queue, "read_projection_work_repairs", unexpected_discovery)
    for _ in range(10):
        assert consumer.repair_once() == 0
    assert failures == [bad.task_id]
    assert str(bad.task_id) in caplog.text
    monkeypatch.setattr(queue, "read_projection_work_repairs", read)
    clock[0] += 1.01
    assert consumer.repair_once() == 1
    assert any(row.scope.task_id == good.task_id for row in queue.read_pending_projection_work())
