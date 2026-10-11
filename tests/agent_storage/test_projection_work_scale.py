"""1k/10k/100k real scalar histories and restored queue/head cold access plans."""

import json
import subprocess
import sys
from contextlib import closing
from uuid import UUID

import pytest
from agent_core.domain.identifiers import EventId
from agent_core.ports.task_projection_checkpoints import ProjectionScope
from agent_core.ports.task_projection_work import ProjectionWork
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from tests.agent_storage.test_scalar_task_replay_headers import INSERT, source_row
from tests.agent_storage.test_task_projection_work import queue as _queue_fixture
from tests.agent_storage.test_task_projection_work import scratch as _scratch_fixture

queue, scratch = _queue_fixture, _scratch_fixture


def seed_scale(queue, count):
    with queue.connect() as connection:
        if queue.backend == "sqlite":
            connection.executemany(
                INSERT,
                (
                    source_row(
                        queue.task,
                        n,
                        run=f"run-{n}",
                        body='{"blob":"' + "x" * 8_388_608 + '"}' if n == count - 1 else None,
                        source_bytes=8_389_376 if n == count - 1 else 1024,
                    )
                    for n in range(count)
                ),
            )
        else:
            with connection.cursor().copy(
                "COPY session_events(deployment_namespace,event_id,session_id,"
                "sequence,event_type,payload,actor,task_id,task_sequence,"
                "event_bytes_bound) FROM STDIN"
            ) as bulk:
                for n in range(count):
                    row = source_row(
                        queue.task,
                        n,
                        run=f"run-{n}",
                        body='{"blob":"' + "x" * 8_388_608 + '"}' if n == count - 1 else None,
                        source_bytes=8_389_376 if n == count - 1 else 1024,
                    )
                    bulk.write_row(
                        (
                            queue.namespace,
                            UUID(row[0]),
                            queue.task,
                            n,
                            row[3],
                            Jsonb(json.loads(row[4])),
                            row[5],
                            queue.task,
                            n,
                            row[8],
                        )
                    )
        queue.execute(connection, "UPDATE agent_tasks SET next_event_sequence=?", (count,))
    queue.install()
    queue.store().enable_projection_work()
    assert queue.store().bootstrap_projection_work()
    # Restore scalar derived state from a previous successful process. This fixture tests
    # indexed reads, not the elapsed time to materialize 100k events in one operation.
    with queue.connect() as connection:
        values = [
            (
                queue.namespace,
                str(queue.task),
                str(UUID(int=n + 1)),
                "ag-ui-v1",
                f"run-{n}",
                n,
                n,
                None if n == count - 2 else n,
                int(n >= count - 33 or n == count // 2),
                "integrity" if n == count // 2 else None,
                int(n == count // 2),
            )
            for n in range(count - 1)
        ]
        statement = "INSERT INTO task_projection_work "
        statement += (
            "(deployment_namespace,task_id,anchor_key,projector_version,run_id,anchor_sequence,"
        )
        statement += "requested_through,closed_through,pending,problem_code,problem_attempts) "
        statement += "VALUES (?,?,?,?,?,?,?,?,?,?,?)"
        with closing(connection.cursor()) as cursor:
            cursor.executemany(
                statement if queue.backend == "sqlite" else statement.replace("?", "%s"), values
            )
        queue.execute(
            connection,
            "UPDATE task_projection_work_routes SET observed_through=?,"
            "wanted_through=?,active_anchor_key=?,needs_repair=1",
            (count - 2, count - 1, str(UUID(int=count - 1))),
        )
    for n in range(count - 33, count - 1):
        queue.set_head(
            ProjectionWork(
                ProjectionScope(queue.namespace, queue.task, EventId(UUID(int=n + 1)), "ag-ui-v1"),
                f"run-{n}",
                n,
                n,
                1,
                n,
                None if n == count - 2 else n,
            )
        )


@pytest.mark.parametrize("count", [1000, 10000, 100000])
def test_cold_scalar_pending_and_tail_repair_seek_no_prefix_or_body(queue, count):
    seed_scale(queue, count)
    location = str(queue.path)
    if queue.backend == "postgres":
        configured = conninfo_to_dict(queue.dsn)
        schema = configured["options"].split("search_path=")[1].split(",")[0]
        with queue.connect() as connection:
            connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(queue.role)))
            connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(queue.role)
                )
            )
            for table in (
                "agent_tasks",
                "task_projection_heads",
                "task_projection_work_projectors",
                "task_projection_work_routes",
                "task_projection_work",
            ):
                connection.execute(
                    sql.SQL("GRANT ALL ON {} TO {}").format(
                        sql.Identifier(table), sql.Identifier(queue.role)
                    )
                )
            connection.execute(
                sql.SQL(
                    "GRANT SELECT(deployment_namespace,task_id,task_sequence,event_id,"
                    "event_type,replay_command_kind,replay_run_id,"
                    "replay_internal_continuation,replay_header_ready) "
                    "ON session_events TO {}"
                ).format(sql.Identifier(queue.role))
            )
            connection.execute("ANALYZE session_events")
            connection.execute("ANALYZE task_projection_work")
            connection.execute("ANALYZE task_projection_heads")
        location = make_conninfo(
            queue.dsn, options=configured["options"] + f" -c role={queue.role}"
        )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.agent_storage.projection_work_probe",
            queue.backend,
            location,
            str(queue.task),
            queue.namespace,
            str(count),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence["payload_denied"] and evidence["count"] == count
    print(json.dumps({k: v for k, v in evidence.items() if k not in ("plans", "visits")}))


@pytest.mark.parametrize("count", [1000, 10000, 100000])
def test_cold_task_discovery_cursor_seek_and_completed_restart(queue, count):
    with queue.connect() as connection:
        if queue.backend == "sqlite":
            connection.executemany(
                "INSERT INTO agent_tasks(task_id,namespace,next_event_sequence,"
                "event_position_state) "
                "VALUES (?,?,0,'ready')",
                ((str(UUID(int=n)), queue.namespace) for n in range(1, count + 1)),
            )
        else:
            with connection.cursor().copy(
                "COPY agent_tasks(deployment_namespace,task_id,next_event_sequence,"
                "event_position_state) FROM STDIN"
            ) as bulk:
                for n in range(1, count + 1):
                    bulk.write_row((queue.namespace, UUID(int=n), 0, "ready"))
    queue.install()
    store = queue.store()
    store.enable_projection_work()
    assert not store.bootstrap_projection_work()
    assert len(store.read_projection_work_repairs()) == 32
    # Restore a durable cursor from an earlier process; tail discovery must not reread the prefix.
    with queue.connect() as connection:
        queue.execute(
            connection,
            "UPDATE task_projection_work_projectors SET bootstrap_after_task_id=?",
            (str(UUID(int=count - 31)),),
        )
        if queue.backend == "postgres":
            connection.execute("ANALYZE agent_tasks")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.agent_storage.projection_work_probe",
            queue.backend,
            str(queue.path) if queue.backend == "sqlite" else queue.dsn,
            str(queue.task),
            queue.namespace,
            str(count),
            "--bootstrap",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    print(json.dumps({k: v for k, v in evidence.items() if k not in ("plans", "visits")}))
