"""Readiness hints must follow the derived commit and precede its queue ACK."""

from tests.agent_integrations.ag_ui_checkpoint_consumer_scratch import (
    _command,
    _consumer,
    _restore,
    _task,
)
from tests.agent_integrations.ag_ui_checkpoint_consumer_scratch import (
    native_source as _native_source_fixture,
)
from tests.agent_storage.test_projection_work_native import native_dsn as native_dsn

native_source = _native_source_fixture


def test_checkpoint_ready_notification_runs_after_durable_commit_before_ack(
    native_source, monkeypatch
):
    tasks, events, queue = native_source
    task = _task(tasks)
    _command(events, task)
    consumer = _consumer(tasks, queue)
    work = queue.read_pending_projection_work()[0]
    notified = []
    ack = queue.complete_projection_work

    def ready(head):
        # A separate store connection must see the committed frontier already.
        assert _restore(tasks).read_checkpoint_head(head.scope) == head
        notified.append(head)
        if len(notified) == 1:
            raise ConnectionError("lost Redis hint")

    def complete(*args, **kwargs):
        assert notified, "ACK happened before readiness notification"
        return ack(*args, **kwargs)

    consumer.checkpoint_committed = ready
    monkeypatch.setattr(queue, "complete_projection_work", complete)
    assert not consumer.materialize_once(work)
    assert notified[0].through_sequence == work.requested_through
    assert queue.read_pending_projection_work()
    assert consumer.materialize_once(work)
    assert not queue.read_pending_projection_work()
    # An already committed work item can republish its readiness safely.
    assert not consumer.materialize_once(work)
    assert len(notified) == 3
