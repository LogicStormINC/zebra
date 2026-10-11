"""Native mutation roots detect changes without history rereads or authority caches."""
# ruff: noqa: F811

import psycopg
import pytest
from agent_storage.postgres.coverage_model_revision import model_revision
from agent_storage.postgres.coverage_recovery_preparation import RecoveryReadSnapshot

from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_cloud,
    postgres_dsn,
)
from tests.worker.test_coverage_model_acceptance import settled


class RollbackProbe(Exception):
    pass


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_native_roots_track_every_source_and_rollback_without_history(model_cloud):
    env = model_cloud
    settled(env)
    with env.database.connect() as connection:
        before = model_revision(connection, NAMESPACE, env.binding)
        assert before and before["revision"] > 0
        for table, assignment in (
            ("session_events", "created_at=created_at+interval '1 microsecond'"),
            ("coverage_model_events", "event_digest=repeat('0',64)"),
            ("coverage_model_calls", "reserved_sequence=reserved_sequence+1"),
            ("coverage_model_ledger", "charged_tokens=charged_tokens+1"),
        ):
            with pytest.raises(RollbackProbe), connection.transaction():
                where = (
                    " WHERE event_type='coverage_model_call_reserved'"
                    if table == "session_events" else ""
                )
                connection.execute(f"UPDATE {table} SET {assignment}{where}")
                after = model_revision(connection, NAMESPACE, env.binding)
                assert after["generation"] == before["generation"]
                assert after["revision"] > before["revision"]
                raise RollbackProbe
            assert model_revision(connection, NAMESPACE, env.binding) == before
        for table in ("coverage_model_events", "coverage_model_calls", "coverage_model_ledger"):
            for operation in ("DELETE FROM", "TRUNCATE"):
                with pytest.raises(RollbackProbe), connection.transaction():
                    connection.execute(f"{operation} {table}")
                    assert model_revision(connection, NAMESPACE, env.binding) != before
                    raise RollbackProbe
                assert model_revision(connection, NAMESPACE, env.binding) == before
        for statement in (
            "UPDATE coverage_model_revisions SET revision=revision+1",
            "DELETE FROM coverage_model_revisions",
            "TRUNCATE coverage_model_revisions",
            "INSERT INTO coverage_model_revisions VALUES "
            "('forged','forged','forged',gen_random_uuid(),1)",
        ):
            with pytest.raises(psycopg.errors.RaiseException, match="database maintained"):
                with connection.transaction():
                    connection.execute(statement)
        # An unrelated opaque scope cannot invalidate this run's revision.
        with pytest.raises(RollbackProbe), connection.transaction():
            connection.execute(
                """INSERT INTO coverage_model_ledger SELECT deployment_namespace,namespace||'other',
                   run_id,policy,calls,charged_tokens,unresolved FROM coverage_model_ledger"""
            )
            assert model_revision(connection, NAMESPACE, env.binding) == before
            raise RollbackProbe


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_prepared_root_refuses_concurrent_native_mutation(model_cloud):
    env = model_cloud
    settled(env)
    with env.database.connect() as prepared:
        snapshot = RecoveryReadSnapshot(prepared)
        before = model_revision(snapshot, NAMESPACE, env.binding)
        assert before is not None and len(snapshot.reads) == 1
    # A separately committed writer must invalidate lock-free prepared evidence.
    with env.database.connect() as writer:
        writer.execute("UPDATE coverage_model_events SET event_digest=repeat('0',64)")
    with env.database.connect() as final:
        with pytest.raises(ValueError, match="changed after preparation"):
            snapshot.revalidate(final)
        after = model_revision(final, NAMESPACE, env.binding)
        assert after["generation"] == before["generation"]
        assert after["revision"] > before["revision"]
