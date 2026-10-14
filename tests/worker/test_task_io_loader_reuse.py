"""Execution phases share addresses while keeping fresh connections and snapshots."""

from time import monotonic
from typing import Any, cast

import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_storage.postgres import task_io
from agent_storage.postgres.stream_proof_batch import StreamProofReader
from agent_storage.postgres.worker_replay_reader import PostgresWorkerReplayReader
from agent_storage.postgres_composition import postgres_control_plane_stores
from zebra_agent_config import load_settings
from zebra_agent_worker import transient_output_composition


def test_execution_phases_share_resolution_but_not_connections(monkeypatch) -> None:
    dsn = "host=127.0.0.1 dbname=qa user=qa"
    shared = task_io.TaskIoConnections(dsn)
    scope = OpaqueAuthorityScope(authority_issuer="https://qa.example", namespace_id="qa")
    stores = postgres_control_plane_stores(
        dsn, deployment_namespace="qa", memory_cursor_signing_key=b"a" * 32,
        artifact_objects=cast(Any, object()), history_scope=scope, continuation_scope=scope,
        task_io_connections=shared,
    )
    replay = PostgresWorkerReplayReader(dsn, deployment_namespace="qa", task_io_connections=shared)
    readers = []

    def reader(*args, **kwargs):
        readers.append(StreamProofReader(*args, **kwargs))
        return readers[-1]

    monkeypatch.setattr(transient_output_composition, "StreamProofReader", reader)
    transient_output_composition.compose_transient_output_factory(
        stores, dsn=dsn, namespace="qa", settings=load_settings(env={}))
    databases = [cast(Any, stores.execution_inputs)._database, replay._database,
                 readers[0]._database]
    assert all(database._task_io is shared for database in databases)
    resolutions, connections, queries = [], [], []

    def resolve(params):
        resolutions.append(params)
        return [{**params, "hostaddr": "127.0.0.1", "port": "5432"}]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query):
            queries.append(query)

    def connect(**kwargs):
        shared._resolve(kwargs.get("deadline") or monotonic() + 2)
        connection = Connection()
        connections.append(connection)
        return connection

    monkeypatch.setattr(task_io, "conninfo_attempts", resolve)
    monkeypatch.setattr(shared, "connect", connect)
    with task_io.task_io_deadline(monotonic() + 2):
        for database in databases[:2]:
            with database.connect() as connection:
                connection.execute("SET TRANSACTION READ ONLY")
        with readers[0].snapshot():
            pass
        with readers[0].snapshot():
            pass
    assert len(resolutions) == 1
    assert len({id(connection) for connection in connections}) == 4
    assert queries[-2:] == ["SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"] * 2
    incompatible = task_io.TaskIoConnections("host=127.0.0.1 dbname=other user=qa")
    for adapter in (PostgresWorkerReplayReader, StreamProofReader):
        with pytest.raises(ValueError, match="does not match"):
            adapter(dsn, deployment_namespace="qa", task_io_connections=incompatible)
