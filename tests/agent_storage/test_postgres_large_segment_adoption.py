"""A large child resumes bounded adoption in its own disposable PostgreSQL DB."""

import psycopg
import pytest
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.identifiers import SessionId, TaskId
from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
from agent_storage.postgres.task_index_transactions import attach_segment_in_transaction
from agent_storage.postgres.task_lineage import PostgresAgentTaskConflictError

from tests.agent_storage import test_postgres_task_positions_quality as quality

NS = quality.NS
positions_dsn = quality.positions_dsn


def test_large_child_keeps_adoption_frontier_across_transactions(positions_dsn: str) -> None:
    root = quality._ready(positions_dsn, 1)
    task_id = TaskId(root)
    store = PostgresAgentTaskStore(positions_dsn, deployment_namespace=NS)
    original = store.read_event_header(task_id, 0)
    assert store.read_run_header(task_id, "legacy").legacy
    with psycopg.connect(positions_dsn) as connection:
        child = quality._source(connection, 600)
    with psycopg.connect(positions_dsn) as connection:
        attach_segment_in_transaction(
            connection,
            NS,
            task_id=task_id,
            segment_id=SessionId(child),
            predecessor_id=SessionId(root),
            reason=RolloverReason.RECOVERY,
        )
    assert store.active_segment(task_id) == child
    with psycopg.connect(positions_dsn) as connection:
        assert connection.execute(
            """SELECT event_position_state,next_event_sequence FROM agent_tasks
               WHERE deployment_namespace=%s AND task_id=%s""",
            (NS, root),
        ).fetchone() == ("assigning", 257)
        assert connection.execute(
            """SELECT count(*) FROM session_events WHERE deployment_namespace=%s
               AND session_id=%s AND task_id IS NOT NULL""",
            (NS, child),
        ).fetchone() == (256,)
    with pytest.raises(PostgresAgentTaskConflictError, match="explicit backfill"):
        store.read_event_page(task_id, -1)
    assert not store.backfill_event_positions(task_id)
    assert store.backfill_event_positions(task_id)
    assert store.read_event_header(task_id, 0) == original
    last = store.read_event_page(task_id, 598)
    assert [item.task_sequence for item in last.events] == [599, 600]
    assert last.events[-1].segment_sequence == 599
