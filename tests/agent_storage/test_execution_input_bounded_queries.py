"""Bounded checkpoint reads and boundary seeks use fixed SQL round trips."""

from types import SimpleNamespace

import pytest
from agent_core.ports.task_projection_checkpoints import CheckpointConflict
from agent_storage import PostgresEventStore

from tests.agent_storage.test_postgres_execution_inputs import inputs
from tests.agent_storage.test_postgres_task_projection_checkpoints import checkpoint_dsn
from tests.worker.test_execution_input_compaction import closed_history
from tests.worker.test_execution_input_frontier import setup_inputs

native_dsn = checkpoint_dsn


@pytest.fixture(params=["postgres", "sqlite"])
def input_store(request, tmp_path):
    if request.param == "postgres":
        dsn = request.getfixturevalue("native_dsn")
        store, _, lease = inputs(dsn)
        source = PostgresEventStore(dsn, deployment_namespace=store.namespace)
    else:
        _, source, lease, store = setup_inputs(tmp_path)
    events = closed_history(lease, models=2, tools=1, output="精确结果🙂")
    for event in events:
        source.append(event)
    return store, lease, events


@pytest.mark.parametrize("corruption", [None, "mismatch", "oversized"])
def test_head_is_one_round_trip_and_corrupt_body_stays_in_database(
    input_store, monkeypatch, corruption,
):
    store, lease, events = input_store
    expected = store.advance(lease, store.read_page(lease, -1, events[-1].sequence))
    if corruption is not None:
        with store._progress_connection(write=True) as connection:
            store._progress_execute(
                connection, "UPDATE execution_input_heads SET state_json=?",
                ("x" * (1_100_000 if corruption == "oversized" else 17),),
            )
    original, rows = store._progress_execute, []

    def execute(connection, query, values=()):
        cursor = original(connection, query, values)
        if "FROM execution_input_heads" not in query:
            return cursor
        row = cursor.fetchone()
        rows.append(row)
        return SimpleNamespace(fetchone=lambda: row)

    monkeypatch.setattr(store, "_progress_execute", execute)
    if corruption is None:
        assert store.read(lease) == expected
        assert "不得泄露凭据" in rows[0]["state_json"]
    else:
        with pytest.raises(CheckpointConflict, match="metadata"):
            store.read(lease)
        assert rows[0]["state_json"] is None
    assert len(rows) == 1


def test_boundary_keeps_captured_highwater_and_batches_index_seeks(input_store, monkeypatch):
    store, lease, events = input_store
    original, seeks = store._progress_execute, []

    def execute(connection, query, values=()):
        if "ORDER BY task_sequence DESC LIMIT 1" in query:
            seeks.append(query)
        return original(connection, query, values)

    monkeypatch.setattr(store, "_progress_execute", execute)
    with store._progress_connection() as connection:
        key = store._key(lease, connection)
        assert store._closed_boundary(connection, key, events[-1].sequence - 1) is None
        seeks.clear()
        boundary = store._closed_boundary(connection, key, events[-1].sequence)
    assert boundary.result.event == events[-3]
    assert boundary.admission.event == events[-1]
    assert len(seeks) == 2  # Run anchor + six bounded terminal-index seeks in one round trip.
