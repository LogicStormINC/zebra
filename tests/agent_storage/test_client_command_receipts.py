"""Existing uniqueness index and namespace-bound projection; optional owned PostgreSQL."""

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ClientSessionId, SessionId, TaskId
from agent_storage import SQLiteEventStore
from agent_storage.client_command_receipts import QUERY


def event():
    segment = SessionId(uuid4())
    client = ClientSessionId(uuid4())
    task = TaskId(uuid4())
    command = SessionCommand(
        session_id=segment,
        kind=SessionCommandKind.RUN,
        expected_revision=0,
        idempotency_key="lost-response",
        payload={
            "thread_id": str(task),
            "run_id": "run-1",
            "client": {
                "client_session_id": str(client),
                "client_state_admission_contract_version": 1,
                "state_snapshot": {"private": "do-not-return"},
            },
        },
    )
    accepted = SessionEvent.create(
        session_id=segment,
        sequence=0,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        created_at=datetime.now(UTC),
        idempotency_key="lost-response",
        payload=command.event_payload(),
    )
    return accepted, task, client, command.command_id


def test_sqlite_indexed_projection_reopens_without_event_hydration(tmp_path, monkeypatch):
    accepted, task, client, cid = event()
    db = tmp_path / "receipts.sqlite"
    SQLiteEventStore(db).append(accepted)
    store = SQLiteEventStore(db)
    monkeypatch.setattr(
        "agent_storage.sqlite.deserialize_event_row", lambda _: pytest.fail("no hydration")
    )
    receipt = store.read_client_command_receipt(
        accepted.session_id, "lost-response", task, "run-1", client
    )
    assert str(receipt.command_id) == str(cid)
    assert "do-not-return" not in repr(receipt)
    for params in [
        (accepted.session_id, "other", task, "run-1", client),
        (accepted.session_id, "lost-response", TaskId(uuid4()), "run-1", client),
        (accepted.session_id, "lost-response", task, "run-2", client),
        (accepted.session_id, "lost-response", task, "run-1", ClientSessionId(uuid4())),
    ]:
        assert store.read_client_command_receipt(*params) is None
    with store._database.connect() as conn:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN " + QUERY,
            (str(accepted.session_id), "lost-response", str(task), "run-1", str(client)),
        ).fetchall()
    assert any("idx_session_events_idempotency" in row[3] for row in plan)


@pytest.mark.parametrize("version", [None, True, 2])
def test_legacy_and_unsupported_commands_are_not_promoted(tmp_path, version):
    accepted, task, client, _ = event()
    payload = accepted.payload
    payload["payload"]["client"]["client_state_admission_contract_version"] = version
    store = SQLiteEventStore(tmp_path / "legacy.sqlite")
    store.append(accepted.model_copy(update={"payload": payload}))
    assert (
        store.read_client_command_receipt(
            accepted.session_id, "lost-response", task, "run-1", client
        )
        is None
    )


def test_owned_postgres_two_readers_namespace_and_index():
    dsn = os.environ.get("ZEBRA_TEST_COMMAND_RECEIPTS_PG_DSN")
    if not dsn:
        pytest.skip("owned disposable PostgreSQL DSN not configured")
    from agent_storage.postgres.client_command_receipts import QUERY as PG_QUERY
    from agent_storage.postgres.events import PostgresEventStore
    from agent_storage.postgres.migration_runner import apply_postgres_migrations

    apply_postgres_migrations(dsn)
    namespace = "receipt-" + uuid4().hex
    accepted, task, client, cid = event()
    PostgresEventStore(dsn, deployment_namespace=namespace).append(accepted)
    for _ in range(2):
        reader = PostgresEventStore(dsn, deployment_namespace=namespace)
        assert str(
            reader.read_client_command_receipt(
                accepted.session_id, "lost-response", task, "run-1", client
            ).command_id
        ) == str(cid)
        assert (
            reader.read_client_command_receipt(
                accepted.session_id, "lost-response", task, "run-2", client
            )
            is None
        )
    assert (
        PostgresEventStore(
            dsn, deployment_namespace=namespace + "-foreign"
        ).read_client_command_receipt(accepted.session_id, "lost-response", task, "run-1", client)
        is None
    )
    with reader._database.connect() as conn:
        conn.execute(
            """INSERT INTO session_events
            (event_id,deployment_namespace,session_id,sequence,event_type,payload,actor,created_at)
            SELECT gen_random_uuid(),%s,%s,n,'session_command_accepted','{}'::jsonb,'system',now()
            FROM generate_series(1,2000) AS n""",
            (namespace, accepted.session_id),
        )
        conn.execute("ANALYZE session_events")
        conn.execute("SET LOCAL enable_seqscan = off")
        plan = conn.execute(
            "EXPLAIN (FORMAT JSON) " + PG_QUERY,
            (namespace, str(accepted.session_id), "lost-response", str(task), "run-1", str(client)),
        ).fetchone()

        def index_names(node):
            if isinstance(node, dict):
                return [node.get("Index Name", "")] + [
                    n for v in node.values() for n in index_names(v)
                ]
            if isinstance(node, list):
                return [n for v in node for n in index_names(v)]
            return []

        assert any("idempotency" in name for name in index_names(plan)), json.dumps(plan, indent=2)
