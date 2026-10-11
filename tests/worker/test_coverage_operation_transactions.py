"""Native operation ownership, not cached permissions or fewer guard callbacks."""
# ruff: noqa: F811

import psycopg
import pytest
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_storage.postgres.connection_scope import postgres_connection_scope
from agent_storage.postgres.coverage_authority import PostgresCoverageAuthority
from agent_storage.postgres.task_admission import load_session_task_binding
from agent_storage.postgres.work_unit import borrow_work_unit
from agent_storage.worker_capability_configuration import NATIVE_CONTINUATION_VERIFIER

from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    NAMESPACE,
    compose,
    dsn,
    model_cloud,
    postgres_dsn,
)


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}],
                         indirect=True)
def test_native_model_policy_guards_share_one_transaction_and_reset(model_cloud, monkeypatch):
    env = model_cloud
    compose(env)
    env.store._execution_receipts = True
    env.store._execution_receipt_verifier = NATIVE_CONTINUATION_VERIFIER
    env.store._model_observation_deriver = derive_semantic_observation
    context = PostgresCoverageAuthority.prepare(
        env.database, env.session, env.task_binding, env.fence,
        lambda session: load_session_task_binding(
            env.dsn, deployment_namespace=NAMESPACE, session_id=session,
        ),
    )
    assert context is not None
    backends, statements = [], []

    def current():
        assert borrow_work_unit((env.dsn, NAMESPACE)) is not None
        with env.database.connect() as connection:
            backends.append(connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
        context.check()  # Lease pin then NEW post-lock permission snapshot, every time.

    original = psycopg.Connection.execute

    def trace(connection, query, *args, **kwargs):
        statements.append(str(query))
        return original(connection, query, *args, **kwargs)

    env.cloud.check_authority = current
    monkeypatch.setattr(psycopg.Connection, "execute", trace)
    with postgres_connection_scope():
        assert env.store.initialize_model_budget(env.binding, fence=env.fence) == env.policy
    assert len(backends) == 2 and len(set(backends)) == 1
    assert statements.count("DISCARD ALL") == 1
    assert sum("AS session_revision" in sql for sql in statements) == 2
    assert borrow_work_unit((env.dsn, NAMESPACE)) is None


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}],
                         indirect=True)
def test_same_transaction_callback_revocation_is_visible_and_rolls_back(model_cloud):
    env = model_cloud
    compose(env)
    env.store._execution_receipts = True
    env.store._execution_receipt_verifier = NATIVE_CONTINUATION_VERIFIER
    env.store._model_observation_deriver = derive_semantic_observation
    current = env.cloud.check_authority

    def revoke():
        assert borrow_work_unit((env.dsn, NAMESPACE)) is not None
        with env.database.connect() as connection:
            connection.execute("UPDATE session_projections SET namespace_id='revoked' "
                               "WHERE session_id=%s", (env.session,))
        current()

    env.cloud.check_authority = revoke
    with pytest.raises(ValueError, match="coverage Host binding is invalid"), \
            postgres_connection_scope():
        env.store.initialize_model_budget(env.binding, fence=env.fence)
    with env.database.connect() as connection:
        assert connection.execute("SELECT namespace_id FROM session_projections "
                                  "WHERE session_id=%s", (env.session,)).fetchone()[
                                      "namespace_id"] == env.host.namespace_id
    assert borrow_work_unit((env.dsn, NAMESPACE)) is None
