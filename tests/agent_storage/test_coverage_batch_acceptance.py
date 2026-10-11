"""Native bounded batch updates reject partial matches and roll back all units."""
# ruff: noqa: F811

import pytest
from agent_storage.postgres.coverage_projection import accept_units

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, postgres_dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import batch, bind, dsn, env  # noqa: F401


def test_batch_uses_one_statement_and_wrong_tenant_matches_nothing(env, monkeypatch):
    bind(env)
    request = batch(env)
    calls = []
    import psycopg

    execute = psycopg.Connection.execute

    def counted(connection, query, *args, **kwargs):
        calls.append(query)
        return execute(connection, query, *args, **kwargs)

    with env.store._database.connect() as connection:
        monkeypatch.setattr(psycopg.Connection, "execute", counted)
        accept_units(connection, NAMESPACE, request)
    assert len(calls) == 1
    monkeypatch.setattr(psycopg.Connection, "execute", execute)
    assert env.store.counts(request.namespace, request.run_id) == (4, 4)
    with pytest.raises(ValueError, match="unexpected"):
        with env.store._database.connect() as connection:
            accept_units(connection, NAMESPACE, request.model_copy(update={"namespace": "foreign"}))


@pytest.mark.parametrize("damage", ["foreign", "duplicate", "already_accepted"])
def test_partial_or_duplicate_batch_cannot_leave_partial_results(env, damage):
    bind(env)
    request = batch(env)
    results = request.results
    if damage == "foreign":
        results = (*results[:-1], results[-1].model_copy(update={
            "key": results[-1].key.model_copy(update={"record_id": "foreign"}),
        }))
    elif damage == "duplicate":
        results = (results[0], results[0])
    else:
        with env.store._database.connect() as connection:
            accept_units(connection, NAMESPACE, request.model_copy(update={"results": results[:1]}))
    before = env.store.counts(request.namespace, request.run_id)
    with pytest.raises(ValueError):
        with env.store._database.connect() as connection:
            accept_units(connection, NAMESPACE, request.model_copy(update={"results": results}))
    assert env.store.counts(request.namespace, request.run_id) == before
