"""Exact native volume counters, fallback and isolation against real PostgreSQL."""
# ruff: noqa: F811

from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.coverage_model_checkpoint import MODEL_CHECKPOINT_KIND
from agent_core.domain.events import EventType
from agent_storage.postgres.coverage_model_source import (
    MODEL_TYPES,
    preflight_original_volume,
    task_policy,
)
from agent_storage.postgres.coverage_model_summary import summary_state
from agent_storage.postgres.coverage_model_volume_summary import volume_summary
from agent_storage.postgres.events import append_event_in_transaction

from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_cloud,
    postgres_dsn,
)
from tests.worker.test_coverage_model_acceptance import settled


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_native_volume_equals_independent_global_source_and_empty_delta_is_bounded(model_cloud):
    env = model_cloud
    settled(env)
    with env.database.connect() as connection:
        root = volume_summary(connection, NAMESPACE, env.binding)
        assert root is not None
        sources = connection.execute(
            """SELECT count(*) AS count,sum(octet_length(to_jsonb(e)::text)) AS bytes
               FROM session_events e WHERE deployment_namespace=%s AND session_id=%s
               AND event_type=ANY(%s)""",
            (NAMESPACE, env.session, list(MODEL_TYPES)),
        ).fetchone()
        assert root["source_bytes"] == sources["bytes"]
        assert root["initialized"] + root["reserved"] + root["receipts"] == sources["count"]
        assert root["original_count"] == 1
        size = connection.execute(
            "SELECT size_bytes FROM artifact_payload_metadata WHERE kind=%s",
            (MODEL_CHECKPOINT_KIND,),
        ).fetchone()
        assert root["original_bytes"] == size["size_bytes"]
        queries = []

        class Bounded:
            def execute(self, sql, args=None):
                queries.append(sql)
                assert "sum(" not in sql and "count(" not in sql
                return connection.execute(sql, args)

        preflight_original_volume(
            Bounded(), NAMESPACE, env.binding, _incremental_keys=set(),
            _policy=task_policy(connection, NAMESPACE, env.binding, incremental=True),
        )
        assert len(queries) == 2  # Root + fresh deadline clock, no historical reads.
        assert volume_summary(connection, "foreign", env.binding) is None


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_metadata_mutation_disables_volume_without_resetting_charges(model_cloud):
    env = model_cloud
    settled(env)
    with env.database.connect() as connection:
        policy = task_policy(connection, NAMESPACE, env.binding)
        before = summary_state(connection, NAMESPACE, env.binding, policy)
        with pytest.raises(RuntimeError, match="probe"), connection.transaction():
            connection.execute(
                "UPDATE artifact_payload_metadata SET size_bytes=size_bytes+1 WHERE kind=%s",
                (MODEL_CHECKPOINT_KIND,),
            )
            assert volume_summary(connection, NAMESPACE, env.binding) is None
            assert summary_state(connection, NAMESPACE, env.binding, policy) == before
            raise RuntimeError("probe")
        assert volume_summary(connection, NAMESPACE, env.binding) is not None
        with pytest.raises(psycopg.errors.RaiseException, match="database maintained"):
            with connection.transaction():
                connection.execute("UPDATE coverage_model_summary SET original_bytes=0")


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_non_model_history_growth_never_enters_normal_volume_probe(model_cloud):
    env = model_cloud
    settled(env)
    with env.database.connect() as connection:
        baseline = volume_summary(connection, NAMESPACE, env.binding)
        origin = next(e for e in env.events.list_for_session(env.session)
                      if e.event_type is EventType.TASK_PREPARED)
        version = connection.execute(
            "SELECT current_version FROM session_streams WHERE deployment_namespace=%s "
            "AND session_id=%s", (NAMESPACE, env.session),
        ).fetchone()["current_version"]
        for offset in range(1, 1001):
            append_event_in_transaction(connection, NAMESPACE, origin.model_copy(update={
                "event_id": uuid4(), "sequence": version + offset, "idempotency_key": None,
            }))
        policy = task_policy(connection, NAMESPACE, env.binding, incremental=True)
        statements = []

        class Bounded:
            def execute(self, sql, args=None):
                statements.append(sql)
                assert "session_events" not in sql and "artifact_payload_metadata" not in sql
                return connection.execute(sql, args)

        preflight_original_volume(
            Bounded(), NAMESPACE, env.binding, _incremental_keys=set(), _policy=policy,
        )
        assert len(statements) == 2
        assert volume_summary(connection, NAMESPACE, env.binding) == baseline
        assert volume_summary(connection, "other-deployment", env.binding) is None
