"""Every explicitly enabled AG-UI family obeys canonical privacy routing."""

import pytest
from agent_storage.postgres.migrations import MIGRATIONS

from tests.agent_storage.projection_work_test_support import QueueFixture
from tests.agent_storage.test_postgres_scalar_task_replay_headers import scratch as _scratch

scratch = _scratch

VERSIONS = (
    "ag-ui-v1",
    "ag-ui-v1-coverage",
    "agui-standard-1.0:r1",
    "agui-standard-1.0:r1:coverage",
    "zebra-reliable-v2-agui-1.0:r1",
    "zebra-reliable-v2-agui-1.0:r1:coverage",
    "agui-standard-1.0:r2",
    "agui-standard-1.0:r2:coverage",
    "zebra-reliable-v2-agui-1.0:r2",
    "zebra-reliable-v2-agui-1.0:r2:coverage",
)


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_all_profile_families_route_exclusively_and_late_privacy_wakes_closed_runs(
    backend, tmp_path, request
):
    native = request.getfixturevalue("scratch") if backend == "postgres" else None
    queue = QueueFixture(backend, tmp_path, native)
    queue.install()
    if backend == "postgres":
        with queue.connect() as connection:
            for statement in next(m for m in MIGRATIONS if m.version == 115).statements:
                connection.execute(statement)
    stores = [queue.store(version) for version in VERSIONS]
    for store in stores:
        store.enable_projection_work()
    with pytest.raises(ValueError, match="budget"):
        queue.store("unsupported-eleventh").enable_projection_work()
    queue.append(0)
    for index, store in enumerate(stores):
        assert bool(store.read_pending_projection_work()) == (index % 2 == 0)
    from uuid import UUID

    from psycopg.types.json import Jsonb

    from tests.agent_storage.test_scalar_task_replay_headers import INSERT, source_row

    row = list(source_row(queue.task, 1, body='{"coverage_admission":null}'))
    row[3] = "task_prepared"
    with queue.connect() as connection:
        if backend == "sqlite":
            connection.execute(INSERT, row)
        else:
            connection.execute(
                "INSERT INTO session_events (deployment_namespace,event_id,session_id,sequence,"
                "event_type,payload,actor,task_id,task_sequence,event_bytes_bound) "
                "VALUES (%s,%s,%s,1,'task_prepared',%s,'system',%s,1,1024)",
                (
                    queue.namespace,
                    UUID(row[0]),
                    queue.task,
                    Jsonb({"coverage_admission": None}),
                    queue.task,
                ),
            )
        queue.execute(
            connection,
            "UPDATE agent_tasks SET next_event_sequence=2 WHERE task_id=?",
            (str(queue.task),),
        )
    for index, store in enumerate(stores):
        if index % 2:
            store.repair_projection_work(queue.task)
            assert store.read_pending_projection_work(), VERSIONS[index]
