"""Derived summaries share existing work discovery, never observation GET repair."""

from agent_integrations.ag_ui.checkpoint_consumer import AgUiCheckpointConsumer

from tests.agent_integrations.ag_ui_checkpoint_consumer_scratch import _command, _native, _task


def test_public_page_can_publish_before_summary_ready_but_work_is_retained(tmp_path, monkeypatch):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    work = queue.read_pending_projection_work()[0]
    consumer = AgUiCheckpointConsumer(tasks, queue, namespace="local", read_summaries=tasks)
    calls = []
    original = tasks.backfill_read_summary

    def delayed(target):
        calls.append(target)
        return False if len(calls) == 1 else original(target)

    monkeypatch.setattr(tasks, "backfill_read_summary", delayed)
    assert consumer.materialize_once(work)
    assert tasks.read_checkpoint_head(work.scope).through_sequence == work.requested_through
    assert queue.read_pending_projection_work()
    assert consumer.materialize_once(work)
    assert not queue.read_pending_projection_work()
    assert tasks.read_task_summary(task.task_id).complete


def test_existing_consumer_remains_opt_in_for_local_compatibility(tmp_path):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    consumer = AgUiCheckpointConsumer(tasks, queue, namespace="local")
    assert consumer.read_summaries is None
    assert consumer.materialize_once(queue.read_pending_projection_work()[0])
    assert not queue.read_pending_projection_work()
