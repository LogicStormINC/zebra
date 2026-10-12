"""Binding authority reads must not rebuild Task indexes or hide renewed grants."""
# ruff: noqa: F811

from dataclasses import replace
from time import monotonic

import psycopg
import pytest
from agent_storage.postgres.connection_scope import postgres_connection_scope
from agent_storage.postgres.database import PostgresDatabase, postgres_deadline
from agent_storage.postgres.task_admission import (
    PostgresTaskAdmissionTransaction,
    load_session_task_binding,
    save_task_binding,
)

from tests.agent_storage.test_postgres_agent_tasks import _append_handoff_events
from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401
from tests.agent_storage.test_postgres_task_admission import _binding, _request

NAMESPACE = "binding-read-test"


@pytest.mark.parametrize("deadline", [False, True])
def test_binding_begin_is_read_only_rr_without_configuration_query(dsn, monkeypatch, deadline):
    from contextlib import nullcontext

    from agent_storage.postgres import task_admission

    session, binding = admit(dsn)
    original = task_admission._read_session_root_binding
    queries = []
    execute = psycopg.Connection.execute

    def traced(connection, query, *args, **kwargs):
        queries.append(str(query))
        return execute(connection, query, *args, **kwargs)

    def checked(connection, namespace, session_id):
        result = original(connection, namespace, session_id)
        assert connection.execute("SHOW transaction_isolation").fetchone()[
            "transaction_isolation"
        ] == "repeatable read"
        assert connection.execute("SHOW transaction_read_only").fetchone()[
            "transaction_read_only"
        ] == "on"
        return result

    monkeypatch.setattr(psycopg.Connection, "execute", traced)
    monkeypatch.setattr(task_admission, "_read_session_root_binding", checked)
    with postgres_connection_scope():
        with postgres_deadline(monotonic() + 30) if deadline else nullcontext():
            for _ in range(2):
                assert load_session_task_binding(
                    dsn, deployment_namespace=NAMESPACE, session_id=session
                ) == binding
        with PostgresDatabase(dsn, deployment_namespace=NAMESPACE).connect() as connection:
            assert connection.execute("SHOW transaction_read_only").fetchone()[
                "transaction_read_only"
            ] == "off"
            assert connection.execute("SHOW transaction_isolation").fetchone()[
                "transaction_isolation"
            ] == "read committed"
    assert not any("SET TRANSACTION" in query for query in queries)


def admit(dsn):
    request = _request()
    binding = _binding(str(request.session.session_id))
    transaction = PostgresTaskAdmissionTransaction(dsn, deployment_namespace=NAMESPACE)
    transaction.admit(replace(request, binding=binding))
    return request.session.session_id, binding


def fingerprints(dsn):
    with psycopg.connect(dsn) as connection:
        return {
            table: connection.execute(
                "SELECT md5(coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)"
                f"::text,'[]')) FROM {table} t"
            ).fetchone()[0]
            for table in ("agent_tasks", "execution_segments", "task_event_index", "session_events")
        }


def test_binding_reads_do_not_mutate_native_indexes(dsn, monkeypatch):  # noqa: F811
    from agent_storage.postgres import task_admission

    session, binding = admit(dsn)
    before = fingerprints(dsn)
    original = task_admission._read_session_root_binding
    roots = []

    def root_for_session(connection, namespace, session_id):
        roots.append(session_id)
        return original(connection, namespace, session_id)

    monkeypatch.setattr(task_admission, "_read_session_root_binding", root_for_session)
    for _ in range(3):
        assert load_session_task_binding(
            dsn, deployment_namespace=NAMESPACE, session_id=session
        ) == binding
    assert roots == [session] * 3  # Fresh each read, not twice per root-session read.
    assert fingerprints(dsn) == before
    with pytest.raises(ValueError, match="not found"):
        load_session_task_binding(dsn, deployment_namespace="foreign", session_id=session)


def test_internal_segment_loads_fresh_root_binding(dsn):  # noqa: F811
    root, binding = admit(dsn)
    child, _ = admit(dsn)
    _append_handoff_events(dsn, NAMESPACE, root=root, child=child)
    assert load_session_task_binding(
        dsn, deployment_namespace=NAMESPACE, session_id=child
    ) == binding
    renewed = binding.model_copy(update={
        "binding_revision": 2,
        "host_capability": binding.host_capability.model_copy(update={"grant_digest": "9" * 64}),
    })
    save_task_binding(dsn, deployment_namespace=NAMESPACE, binding=renewed,
                      expected_previous_revision=1)
    assert load_session_task_binding(
        dsn, deployment_namespace=NAMESPACE, session_id=child
    ) == renewed


def test_corrupt_handoff_cannot_select_root_authority(dsn):  # noqa: F811
    root, _ = admit(dsn)
    child, _ = admit(dsn)
    _append_handoff_events(dsn, NAMESPACE, root=root, child=child, mismatched_checksum=True)
    with pytest.raises(ValueError, match="committed parent"):
        load_session_task_binding(dsn, deployment_namespace=NAMESPACE, session_id=child)


def test_retained_binding_cannot_hide_missing_root_projection(dsn):  # noqa: F811
    root, _ = admit(dsn)
    child, _ = admit(dsn)
    _append_handoff_events(dsn, NAMESPACE, root=root, child=child)
    with psycopg.connect(dsn) as connection:
        for table in ("task_event_index", "execution_segments", "agent_tasks"):
            connection.execute(
                f"DELETE FROM {table} WHERE deployment_namespace=%s AND task_id=%s",
                (NAMESPACE, root),
            )
        connection.execute(
            "DELETE FROM session_projections WHERE deployment_namespace=%s AND session_id=%s",
            (NAMESPACE, root),
        )
    with pytest.raises(ValueError, match="projection was not found"):
        load_session_task_binding(dsn, deployment_namespace=NAMESPACE, session_id=child)


def test_root_binding_read_uses_two_business_statements(dsn, monkeypatch):
    session, binding = admit(dsn)
    queries = []
    execute = psycopg.Connection.execute

    def traced(connection, query, *args, **kwargs):
        queries.append(str(query))
        return execute(connection, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", traced)
    assert load_session_task_binding(
        dsn, deployment_namespace=NAMESPACE, session_id=session
    ) == binding
    assert len(queries) == 2  # Root + latest binding, then unchanged full lineage.
    assert "JOIN LATERAL" in queries[0] and "task_binding_snapshots" in queries[0]
    assert "committed.match_count" in queries[1]


def test_duplicate_received_handoff_cannot_select_binding(dsn):
    root, _ = admit(dsn)
    child, _ = admit(dsn)
    for _ in range(2):
        _append_handoff_events(dsn, NAMESPACE, root=root, child=child)
    with pytest.raises(ValueError, match="ambiguous received"):
        load_session_task_binding(dsn, deployment_namespace=NAMESPACE, session_id=child)


@pytest.mark.parametrize("corrupt", [False, True])
def test_missing_binding_does_not_skip_lineage_validation(dsn, corrupt):
    root, _ = admit(dsn)
    child, _ = admit(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "DELETE FROM task_binding_snapshots WHERE deployment_namespace=%s AND task_id=%s",
            (NAMESPACE, root),
        )
    assert load_session_task_binding(
        dsn, deployment_namespace=NAMESPACE, session_id=root
    ) is None
    _append_handoff_events(dsn, NAMESPACE, root=root, child=child, mismatched_checksum=corrupt)
    if corrupt:
        with pytest.raises(ValueError, match="committed parent"):
            load_session_task_binding(dsn, deployment_namespace=NAMESPACE, session_id=child)
    else:
        assert load_session_task_binding(
            dsn, deployment_namespace=NAMESPACE, session_id=child
        ) is None


def test_malformed_root_is_a_controlled_lineage_refusal(dsn):
    root, _ = admit(dsn)
    child, _ = admit(dsn)
    _append_handoff_events(dsn, NAMESPACE, root=root, child=child)
    with psycopg.connect(dsn) as connection:
        query = (
            "UPDATE session_events SET payload=jsonb_set(payload, '{root_session_id}',"
            " '\"not-a-uuid\"'::jsonb) WHERE deployment_namespace=%s AND session_id=%s"
            " AND event_type='session_handoff_received'"
        )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable"):
            with connection.transaction():
                connection.execute(query, (NAMESPACE, child))
        # Reproduce preexisting corrupt legacy data only in this fixture-owned
        # schema. Current immutable-source refusal is independently asserted above.
        assert connection.execute("SELECT current_schema()").fetchone()[0].startswith(
            "command_wakeup_"
        )
        connection.execute("ALTER TABLE session_events DISABLE TRIGGER USER")
        connection.execute(query, (NAMESPACE, child))
        connection.execute("ALTER TABLE session_events ENABLE TRIGGER USER")
    with pytest.raises(ValueError, match="malformed root identity"):
        load_session_task_binding(dsn, deployment_namespace=NAMESPACE, session_id=child)


def test_binding_snapshot_cannot_select_another_task(dsn):
    root, _ = admit(dsn)
    other, _ = admit(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE task_binding_snapshots SET snapshot_json=(SELECT snapshot_json"
            " FROM task_binding_snapshots WHERE deployment_namespace=%s AND task_id=%s)"
            " WHERE deployment_namespace=%s AND task_id=%s",
            (NAMESPACE, other, NAMESPACE, root),
        )
    with pytest.raises(ValueError, match="stored task binding digest"):
        load_session_task_binding(dsn, deployment_namespace=NAMESPACE, session_id=root)
