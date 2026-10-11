"""Native source-retention guards, including a stale repeatable-read writer.

These raw rows test storage constraints, not qualification of a fast-path proof.
"""
# ruff: noqa: F811

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.coverage_contracts import coverage_digest
from agent_storage.postgres import migration_runner
from agent_storage.postgres.coverage_model_source import replay_model
from psycopg.types.json import Jsonb

from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_cloud,
    postgres_dsn,
)


@pytest.fixture(autouse=True)
def schema_version(request, monkeypatch):
    migrations = migration_runner.MIGRATIONS
    if getattr(request, "param", 85) == 84:
        monkeypatch.setattr(
            migration_runner, "MIGRATIONS", tuple(m for m in migrations if m.version <= 84),
        )

    def upgrade(dsn):
        # This test proves the specific84-to85 retention upgrade, not later fleet DDL.
        monkeypatch.setattr(migration_runner, "MIGRATIONS", tuple(
            m for m in migrations if m.version <= 85
        ))
        migration_runner.apply_postgres_migrations(dsn)

    return upgrade


def source(connection, env, *, kind="coverage_batch_accepted"):
    event = uuid4()
    connection.execute(
        """INSERT INTO session_events
           (deployment_namespace,event_id,session_id,sequence,event_type,payload,actor,created_at)
           SELECT %s,%s,%s,coalesce(max(sequence),0)+1,%s,%s,'harness',clock_timestamp()
           FROM session_events WHERE deployment_namespace=%s AND session_id=%s""",
        (NAMESPACE, event, env.session, kind,
         Jsonb({"namespace": NAMESPACE, "run_id": env.binding.run_id}), NAMESPACE, env.session),
    )
    connection.execute(
        """UPDATE session_streams SET current_version=(SELECT sequence FROM session_events
           WHERE deployment_namespace=%s AND event_id=%s)
           WHERE deployment_namespace=%s AND session_id=%s""",
        (NAMESPACE, event, NAMESPACE, env.session),
    )
    return event


def seal(connection, env, event, **overrides):
    body = {"protocol": "coverage-execution-receipt/1"}
    connection.execute(
        """INSERT INTO coverage_execution_receipts
           (deployment_namespace,namespace,run_id,session_id,event_id,sequence,body,body_digest)
           SELECT deployment_namespace,%s,%s,%s,event_id,coalesce(%s,sequence),%s,%s
           FROM session_events WHERE deployment_namespace=%s AND event_id=%s""",
        (overrides.get("namespace", NAMESPACE), overrides.get("run_id", env.binding.run_id),
         overrides.get("session_id", env.session), overrides.get("sequence"),
         Jsonb(body), coverage_digest(body), NAMESPACE, event),
    )


def test_source_seal_retains_only_receipt_sources_and_rolls_back(model_cloud):
    env = model_cloud
    with env.database.connect() as connection:
        event = source(connection, env)
        other = source(connection, env)
    with pytest.raises(ValueError, match="abort seal"):
        with env.database.connect() as connection:
            seal(connection, env, event)
            raise ValueError("abort seal")
    with env.database.connect() as connection:
        assert connection.execute(
            "SELECT 1 FROM coverage_execution_receipts WHERE event_id=%s", (event,),
        ).fetchone() is None
        seal(connection, env, event)
    for statement in (
        "UPDATE session_events SET created_at=created_at+interval '1 microsecond' "
        "WHERE event_id=%s",
        "UPDATE session_events SET created_at=created_at WHERE event_id=%s",
        "DELETE FROM session_events WHERE event_id=%s",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
            with env.database.connect() as connection:
                connection.execute(statement, (event,))
    with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
        with env.database.connect() as connection:
            connection.execute("TRUNCATE session_events CASCADE")
    with env.database.connect() as connection:
        connection.execute("UPDATE session_events SET actor='unsealed' WHERE event_id=%s", (other,))
        connection.execute("DELETE FROM session_events WHERE event_id=%s", (other,))


def test_stale_repeatable_read_writer_cannot_miss_committed_receipt(model_cloud):
    env = model_cloud
    with env.database.connect() as connection:
        event = source(connection, env)
    with pytest.raises(psycopg.errors.SerializationFailure):
        with env.database.connect() as stale:
            stale.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            stale.execute("SELECT 1 FROM session_events WHERE event_id=%s", (event,))
            with env.database.connect() as writer:
                seal(writer, env, event)
            stale.execute("UPDATE session_events SET actor='stale' WHERE event_id=%s", (event,))


def test_concurrent_source_writer_waits_for_seal_then_refuses(model_cloud):
    env = model_cloud
    with env.database.connect() as connection:
        event = source(connection, env)
    started = Event()

    def mutate():
        with env.database.connect() as writer:
            writer.execute("SET LOCAL statement_timeout='5s'")
            started.set()
            writer.execute("UPDATE session_events SET actor='racing' WHERE event_id=%s", (event,))

    with ThreadPoolExecutor(max_workers=1) as pool:
        with env.database.connect() as writer:
            seal(writer, env, event)
            future = pool.submit(mutate)
            assert started.wait(2)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
        with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
            future.result(timeout=5)


def test_receipt_cannot_seal_non_acceptance_event(model_cloud):
    env = model_cloud
    with env.database.connect() as connection:
        event = source(connection, env, kind="other")
    with pytest.raises(psycopg.errors.RaiseException, match="requires native accepted source"):
        with env.database.connect() as connection:
            seal(connection, env, event)


@pytest.mark.parametrize("field", ["namespace", "run_id", "session_id", "sequence"])
def test_receipt_source_scope_mismatch_refuses(model_cloud, field):
    env = model_cloud
    with env.database.connect() as connection:
        event = source(connection, env)
    value = uuid4() if field == "session_id" else 100000 if field == "sequence" else "different"
    with pytest.raises(psycopg.errors.RaiseException, match="requires native accepted source"):
        with env.database.connect() as connection:
            seal(connection, env, event, **{field: value})


@pytest.mark.parametrize("schema_version", [84], indirect=True)
@pytest.mark.parametrize("tampered", [False, True])
def test_upgrade_preserves_old_model_witness_and_seals_old_receipt(
    schema_version, model_cloud, tampered,
):
    from tests.worker.test_coverage_model_acceptance import request_for, settled

    env = model_cloud
    observation, _ = settled(env)
    env.store.commit(request_for(env, observation), fence=env.fence)
    with env.database.connect() as connection:
        assert connection.execute(
            "SELECT max(version) AS version FROM zebra_schema_migrations"
        ).fetchone()["version"] == 84
        witness = connection.execute(
            "SELECT source_row FROM coverage_model_events ORDER BY sequence LIMIT 1"
        ).fetchone()["source_row"]
        if tampered:
            connection.execute(
                "UPDATE session_events SET created_at=created_at+interval '1 microsecond' "
                "WHERE event_id=%s", (witness["event_id"],),
            )
        event = connection.execute(
            "SELECT event_id FROM session_events WHERE event_type='coverage_batch_accepted'"
        ).fetchone()["event_id"]
        original_source = connection.execute(
            "SELECT to_jsonb(e) AS body FROM session_events e WHERE event_id=%s", (event,),
        ).fetchone()["body"]
        seal(connection, env, event)
    schema_version(env.dsn)
    with env.database.connect() as connection:
        assert connection.execute(
            "SELECT max(version) AS version FROM zebra_schema_migrations"
        ).fetchone()["version"] == 85
        assert connection.execute(
            "SELECT to_jsonb(e) AS body FROM session_events e WHERE event_id=%s", (event,),
        ).fetchone()["body"] == original_source
        assert connection.execute(
            "SELECT source_row FROM coverage_model_events ORDER BY sequence LIMIT 1"
        ).fetchone()["source_row"] == witness
        if tampered:
            with pytest.raises(ValueError, match="model source proof witness conflicts"):
                replay_model(connection, NAMESPACE, env.binding, artifacts=env.cloud)
        else:
            state, _ = replay_model(connection, NAMESPACE, env.binding, artifacts=env.cloud)
            assert state is not None and state.unresolved == 0
    with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
        with env.database.connect() as connection:
            connection.execute("DELETE FROM session_events WHERE event_id=%s", (event,))
