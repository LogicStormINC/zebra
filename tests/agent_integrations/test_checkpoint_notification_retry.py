"""Physical hint retry never consumes durable projection failure attempts."""

import pytest
from agent_integrations.ag_ui.checkpoint_consumer import AgUiCheckpointConsumer

from tests.agent_integrations.ag_ui_checkpoint_consumer_scratch import _command, _native, _task
from tests.agent_storage.test_postgres_migrations import (
    isolated_migration_dsn as _checkpoint_dsn_fixture,
)
from tests.agent_storage.test_postgres_migrations import (
    postgres_dsn as _checkpoint_postgres_fixture,
)

isolated_migration_dsn = _checkpoint_dsn_fixture

postgres_dsn = _checkpoint_postgres_fixture


def test_ready_and_new_head_survive_long_notification_outage_and_restart(tmp_path, monkeypatch):
    tasks, events, queue = _native(tmp_path)
    task = _task(tasks)
    _command(events, task)
    (work,) = queue.read_pending_projection_work()
    now = [1000.0]
    monkeypatch.setattr("agent_integrations.ag_ui.checkpoint_consumer.monotonic", lambda: now[0])
    published = []

    def unavailable(head):
        published.append(head.through_sequence)
        raise TimeoutError("safe synthetic notification loss")

    consumer = AgUiCheckpointConsumer(
        tasks,
        queue,
        namespace="local",
        checkpoint_committed=unavailable,
        notification_required=True,
    )
    for _ in range(24):
        consumer.poll_once(budget_seconds=2)
        now[0] += 31
    assert len(published) == 12
    assert queue.read_projection_work_problem(work.scope) is None
    assert (
        queue.read_pending_projection_work()
        and tasks.read_checkpoint_head(work.scope).through_sequence == 0
    )
    # Already-ready retry must not recommit frames after restart.
    monkeypatch.setattr(tasks, "commit_projection_page", lambda *a: pytest.fail("duplicate commit"))
    second = AgUiCheckpointConsumer(
        tasks,
        queue,
        namespace="local",
        checkpoint_committed=lambda h: True,
        notification_required=True,
    )
    assert second.materialize_once(queue.read_pending_projection_work()[0])
    assert not queue.read_pending_projection_work()


def test_notification_policy_cooldown_bounds_and_scope_fairness(tmp_path, monkeypatch):
    tasks, events, queue = _native(tmp_path)
    members = [_task(tasks, ordinal=n) for n in range(1, 35)]
    first = members[0]
    for task in members:
        _command(events, task)
    works = {w.scope.task_id: w for w in queue.read_pending_projection_work()}
    now = [1000.0]
    monkeypatch.setattr("agent_integrations.ag_ui.checkpoint_consumer.monotonic", lambda: now[0])

    def publish(head):
        if head.scope.task_id == first.task_id:
            raise TimeoutError()
        return True

    consumer = AgUiCheckpointConsumer(
        tasks, queue, namespace="local", checkpoint_committed=publish, notification_required=True
    )
    consumer.poll_once(limit=1, budget_seconds=2)
    consumer.poll_once(limit=32, budget_seconds=2)
    consumer.poll_once(limit=32, budget_seconds=2)
    assert [w.scope.task_id for w in queue.read_pending_projection_work()] == [first.task_id]
    before = dict(consumer._notification_retry)
    consumer.poll_once(limit=1, budget_seconds=2)  # cursor wrap
    consumer.poll_once(limit=1, budget_seconds=2)  # skips cooling scope, never ACKs
    assert consumer._notification_retry == before
    assert not consumer._notify_checkpoint(tasks.read_checkpoint_head(works[first.task_id].scope))
    assert consumer._notification_retry[works[first.task_id].scope][0] == 2
    with pytest.raises(ValueError):
        AgUiCheckpointConsumer(tasks, queue, namespace="local", notification_required=True)
    local = AgUiCheckpointConsumer(tasks, queue, namespace="local")
    assert local.materialize_once(queue.read_pending_projection_work()[0])


def test_scope_cooldown_capacity_idle_pruning_and_failed_count_retention(tmp_path, monkeypatch):
    from uuid import uuid4

    from agent_core.domain.identifiers import TaskId
    from agent_core.ports.task_projection_checkpoints import (
        ProjectionCheckpointHead,
        ProjectionScope,
    )
    from agent_integrations.ag_ui.checkpoint_plan import AG_UI_CHECKPOINT_VERSION

    tasks, _, queue = _native(tmp_path)
    now = [1000.0]
    monkeypatch.setattr("agent_integrations.ag_ui.checkpoint_consumer.monotonic", lambda: now[0])

    def fail(head):
        raise TimeoutError()

    consumer = AgUiCheckpointConsumer(tasks, queue, namespace="local", checkpoint_committed=fail)
    heads = [
        ProjectionCheckpointHead(
            ProjectionScope("local", TaskId(uuid4()), uuid4(), AG_UI_CHECKPOINT_VERSION)
        )
        for _ in range(513)
    ]
    for head in heads:
        assert not consumer._notify_checkpoint(head)
        now[0] += 0.001
    assert (
        len(consumer._notification_retry) == 512
        and heads[0].scope not in consumer._notification_retry
    )
    now[0] += 31
    assert not consumer._notify_checkpoint(heads[-1])
    assert consumer._notification_retry[heads[-1].scope][0] == 2
    now[0] += 301
    assert not consumer._notify_checkpoint(heads[-1])
    assert len(consumer._notification_retry) == 1


def _full_pg_stores(dsn, *, bootstrap=True):
    from agent_core.domain.cloud_scope import OpaqueAuthorityScope
    from agent_storage import bootstrap_control_plane_epoch, postgres_control_plane_stores

    from tests.agent_storage.test_postgres_control_plane_composition import _ObjectReader

    if bootstrap:
        bootstrap_control_plane_epoch(dsn, deployment_namespace="local")
    else:
        from agent_storage import read_control_plane_epoch

        read_control_plane_epoch(dsn, deployment_namespace="local")
    scope = OpaqueAuthorityScope(authority_issuer="relay-test", namespace_id="relay-test")
    return postgres_control_plane_stores(
        dsn,
        deployment_namespace="local",
        memory_cursor_signing_key=b"relay-test-key" * 3,
        artifact_objects=_ObjectReader(),
        history_scope=scope,
        continuation_scope=scope,
    )


def test_supplement_pg_redis_checkpoint_outage_and_fresh_process_retry(
    isolated_migration_dsn, tmp_path, monkeypatch
):
    import os
    import subprocess
    import sys
    from time import monotonic
    from uuid import uuid4

    from agent_integrations.redis_live_fanout import RedisLiveEventFanout
    from agent_integrations.redis_transient_deadlines import redis_io_deadline
    from agent_storage.postgres.migration_runner import apply_postgres_migrations

    from tests.agent_integrations.ag_ui_checkpoint_consumer_scratch import (
        _prefix_sources,
        prepare_source_projections,
    )
    from tests.agent_runtime.test_stream_hint_relay import _ReplyProxy

    dsn = isolated_migration_dsn
    apply_postgres_migrations(dsn)
    stores = _full_pg_stores(dsn)
    tasks, queue = stores.tasks, stores.projection_work
    queue.enable_projection_work()
    task = _task(tasks, ordinal=uuid4().int)
    prefix = _prefix_sources(tasks, task)
    accepted = _command(stores.events, task)
    prepare_source_projections(tasks, [*prefix, accepted])
    (work,) = queue.read_pending_projection_work()
    now = [1000.0]
    monkeypatch.setattr("agent_integrations.ag_ui.checkpoint_consumer.monotonic", lambda: now[0])
    with _ReplyProxy(os.environ["ZEBRA_STREAM_TEST_REDIS_URL"]) as proxy:
        fanout = RedisLiveEventFanout.from_url(proxy.url)
        attempted = []

        def publish(head):
            fanout._client.ping()  # Warm reconnect outside this controlled response fault.
            proxy.reply_seen.clear()
            proxy.reply_delay = 0.08
            attempted.append(head.through_sequence)
            with redis_io_deadline(monotonic() + 0.03):
                return fanout.publish_checkpoint(head)

        consumer = AgUiCheckpointConsumer(
            tasks,
            queue,
            namespace="local",
            checkpoint_committed=publish,
            notification_required=True,
        )
        try:
            for _ in range(12):
                assert not consumer.materialize_once(queue.read_pending_projection_work()[0])
                assert proxy.reply_seen.wait(1)
                now[0] += 31
            assert len(attempted) == 12 and queue.read_projection_work_problem(work.scope) is None
            assert (
                queue.read_pending_projection_work()
                and tasks.read_checkpoint_head(work.scope).through_sequence == 1
            )
            with tasks._database.connect() as connection:
                before = connection.execute(
                    "SELECT count(*) FROM task_projection_cells"
                ).fetchone()["count"]
            code = """import os
from agent_integrations.ag_ui.checkpoint_consumer import AgUiCheckpointConsumer
from agent_integrations.redis_live_fanout import RedisLiveEventFanout
from tests.agent_integrations.test_checkpoint_notification_retry import _full_pg_stores

stores = _full_pg_stores(os.environ["RELAY_TEST_DSN"], bootstrap=False)
fanout = RedisLiveEventFanout.from_url(os.environ["ZEBRA_STREAM_TEST_REDIS_URL"])
consumer = AgUiCheckpointConsumer(
    stores.tasks,
    stores.projection_work,
    namespace="local",
    checkpoint_committed=fanout.publish_checkpoint,
    notification_required=True,
)
(work,) = stores.projection_work.read_pending_projection_work()
print("ACK", consumer.materialize_once(work), flush=True)
fanout.close()
"""
            fresh = subprocess.run(
                [sys.executable, "-c", code],
                env={**os.environ, "RELAY_TEST_DSN": dsn},
                capture_output=True,
                timeout=5,
                check=False,
            )
            import re

            diagnostic = {
                "exit": fresh.returncode,
                "classes": sorted(
                    set(re.findall(rb"(?m)^([A-Za-z_]\w*(?:Error|Exception)):", fresh.stderr))
                ),
                "frames": re.findall(rb'File "([^"\n]*\.py)", line (\d+)', fresh.stderr),
            }
            assert fresh.returncode == 0, diagnostic
            assert fresh.stdout.strip() == b"ACK True" and not queue.read_pending_projection_work()
            with tasks._database.connect() as connection:
                assert (
                    connection.execute("SELECT count(*) FROM task_projection_cells").fetchone()[
                        "count"
                    ]
                    == before
                )
        finally:
            fanout._client.delete(fanout._checkpoint_key("local", task.task_id))
            fanout.close()
