"""Late native Task projection allocation must not mutate MODEL source authority."""

import psycopg
import pytest
from agent_core.domain.identifiers import TaskId
from agent_storage.postgres.coverage_model_index import indexed_state
from agent_storage.postgres.coverage_model_source import task_policy
from agent_storage.postgres.coverage_model_summary import summary_state
from agent_storage.postgres.coverage_model_volume_summary import volume_summary
from agent_storage.postgres.projection_source_metadata import backfill_projection_source_metadata
from agent_storage.postgres.task_event_positions import backfill_task_event_positions

from tests.agent_storage.test_coverage_model_budget import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_env,
    postgres_dsn,
    reserve,
    spend,
)


def test_native_allocation_preserves_source_proof_and_exact_volume(model_env):  # noqa: F811
    env = model_env()
    spend(env, reserve(env))
    with env.store._database.connect() as connection:
        policy = task_policy(connection, NAMESPACE, env.binding)
        before = summary_state(connection, NAMESPACE, env.binding, policy)
        revision = connection.execute("SELECT revision FROM coverage_model_revisions").fetchone()
        task = TaskId(env.binding.task_id)
        while not backfill_task_event_positions(connection, NAMESPACE, task):
            pass
        while not backfill_projection_source_metadata(connection, NAMESPACE, task):
            pass
        changed = connection.execute(
            """SELECT count(*) AS count FROM coverage_model_events w JOIN session_events e
               ON e.deployment_namespace=w.deployment_namespace AND e.sequence=w.sequence
                 AND e.session_id=%s WHERE to_jsonb(e) IS DISTINCT FROM w.source_row""",
            (env.binding.session_id,),
        ).fetchone()
        assert changed["count"] > 0, "fixture must exercise real deferred allocation"
        assert summary_state(connection, NAMESPACE, env.binding, policy) == before
        assert indexed_state(connection, NAMESPACE, env.binding, _policy=policy) == before
        after = connection.execute("SELECT revision FROM coverage_model_revisions").fetchone()
        assert after == revision
        root = volume_summary(connection, NAMESPACE, env.binding)
        source_bytes = connection.execute(
            """SELECT sum(octet_length(to_jsonb(e)::text)) AS bytes FROM session_events e
               WHERE event_type LIKE 'coverage_model_%'"""
        ).fetchone()["bytes"]
        assert root["source_bytes"] == source_bytes
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable"):
            with connection.transaction():
                connection.execute(
                    "UPDATE session_events SET payload=payload || '{\"tampered\":true}'::jsonb "
                    "WHERE event_type='coverage_model_call_reserved'"
                )
        with pytest.raises(ValueError, match="tampered|witness"):
            with connection.transaction():
                connection.execute(
                    "UPDATE coverage_model_events SET source_row=jsonb_set(source_row, "
                    "'{actor}', '\"tool\"'::jsonb)"
                )
                indexed_state(connection, NAMESPACE, env.binding, _policy=policy)
