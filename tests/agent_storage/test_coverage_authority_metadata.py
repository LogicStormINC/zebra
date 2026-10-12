"""Readonly authority and selected full metadata share one fresh SQL snapshot."""
# ruff: noqa: F401,F811

from uuid import UUID, uuid4

import psycopg
import pytest
from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.work_unit import postgres_work_unit

from tests.agent_storage.test_coverage_authority import append_authority_change, prepare
from tests.worker.coverage_model_cloud_fixtures import dsn, model_cloud, postgres_dsn


def test_metadata_observation_one_snapshot_and_full_record(model_cloud, monkeypatch):
    env, statements = model_cloud, []
    authority = prepare(env)
    identifier = UUID(env.binding.snapshot.manifest_artifact_ref.removeprefix("artifact://"))
    missing = uuid4()
    with env.database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM artifact_payload_metadata WHERE artifact_id=%s", (identifier,),
        ).fetchone()
    expected = artifact_payload_from_row(row)
    original = psycopg.Connection.execute

    def traced(connection, query, *args, **kwargs):
        statements.append(str(query))
        return original(connection, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", traced)
    assert callable(getattr(authority, "observe_payloads", None))
    version, records = authority.observe_payloads((identifier, missing))
    assert version >= 0 and records == {identifier: expected}
    assert len(statements) == 1 and "artifact_payload_metadata" in statements[0]
    assert "FOR SHARE" not in statements[0]
    # This is readonly preparation, never an implicit mutation proof/borrow.
    with postgres_work_unit(env.database), pytest.raises(ValueError, match="readonly"):
        authority.observe_payloads((identifier,))


@pytest.mark.parametrize("change", ["stop", "binding", "expired", "record"])
def test_metadata_observation_is_not_a_cross_read_permission_cache(model_cloud, change):
    env = model_cloud
    authority = prepare(env)
    identifier = UUID(env.binding.snapshot.manifest_artifact_ref.removeprefix("artifact://"))
    assert callable(getattr(authority, "observe_payloads", None))
    _, previous = authority.observe_payloads((identifier,))
    with env.database.connect() as connection:
        if change == "stop":
            append_authority_change(connection, env, "stop")
        elif change == "binding":
            connection.execute("UPDATE session_projections SET namespace_id='foreign' "
                               "WHERE session_id=%s", (env.session,))
        else:
            field = ("file_name='updated'" if change == "record" else
                     "retained_until=clock_timestamp() - interval '1 second'")
            connection.execute(f"UPDATE artifact_payload_metadata SET {field} "
                               "WHERE artifact_id=%s", (identifier,))
    if change in {"stop", "binding"}:
        with pytest.raises(ValueError):
            authority.observe_payloads((identifier,))
    else:
        _, current = authority.observe_payloads((identifier,))
        assert current[identifier] != previous[identifier]


def test_metadata_observation_refuses_unbounded_or_untyped_identity_sets(model_cloud):
    authority = prepare(model_cloud)
    assert callable(getattr(authority, "observe_payloads", None))
    for invalid in ((), ("bad",), (uuid4(),) * 2, tuple(uuid4() for _ in range(1001))):
        with pytest.raises(ValueError, match="identity"):
            authority.observe_payloads(invalid)
