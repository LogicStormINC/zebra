"""Native parent identity lookup is deployment-bound and does not write."""

import psycopg
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.identifiers import TaskId
from agent_storage import PostgresAgentTaskStore, attach_segment_in_transaction

from tests.agent_storage import test_postgres_agent_tasks as support

postgres_dsn = support.postgres_dsn
task_namespace = support.task_namespace


def test_native_lookup_does_not_create_task_and_binds_parent_namespace(
    postgres_dsn,
    task_namespace,
    tmp_path,
):
    root = support._seed_session(postgres_dsn, task_namespace, tmp_path / "root", "Root")
    child = support._seed_session(postgres_dsn, task_namespace, tmp_path / "child", "Child")
    store = PostgresAgentTaskStore(postgres_dsn, deployment_namespace=task_namespace)
    assert store.task_id_for_session(root) is None
    assert store.get_task(TaskId(root)) is None
    task = store.ensure_for_session(root)
    with psycopg.connect(postgres_dsn) as connection:
        attach_segment_in_transaction(
            connection,
            task_namespace,
            task_id=task.task_id,
            segment_id=child,
            predecessor_id=root,
            reason=RolloverReason.RECOVERY,
        )
    assert store.task_id_for_session(root) == task.task_id
    assert store.task_id_for_session(child) == task.task_id
    other = PostgresAgentTaskStore(postgres_dsn, deployment_namespace="wrong-namespace")
    assert other.task_id_for_session(child) is None
    assert store.task_id_for_session(child) == task.task_id
