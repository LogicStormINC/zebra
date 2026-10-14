"""Fresh canonical heads use bounded metadata and deny unchanged corrupt sources."""

from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
from agent_integrations.ag_ui.contracts import AgUiRunIdentity

from tests.api.test_cloud_stream_read_bounds import append
from tests.api.test_cloud_stream_read_bounds import postgres_dsn as _dsn_fixture
from tests.api.test_cloud_stream_read_bounds import source as _source_fixture
from tests.api.test_cloud_stream_read_bounds import task_namespace as _namespace_fixture
from tests.stream_storage.telemetry import Telemetry

postgres_dsn = _dsn_fixture
source = _source_fixture
task_namespace = _namespace_fixture


def test_fresh_heads_actual_client_sql_and_connection_counts(source):
    stores, sid = source
    telemetry = Telemetry()
    with telemetry.installed():
        telemetry.stage = "session"
        session = stores.tasks.read_stream_source_head(session_id=sid)
        telemetry.stage = "task"
        task = stores.tasks.read_stream_source_head(task_id=TaskId(sid))
        telemetry.stage = "checkpoint"
        snapshot = AgUiCheckpointObserver(
            stores.tasks, namespace=stores.deployment_namespace
        ).snapshot(
            TaskId(sid), AgUiRunIdentity(session_id=sid, thread_id=str(sid), run_id="legacy")
        )
    assert session.task == task.task
    assert session.session_sequence == task.task.current_sequence
    assert snapshot.run.legacy and snapshot.head.through_sequence == -1
    for stage, expected in (("session", 2), ("task", 2), ("checkpoint", 2)):
        assert (
            sum(v for k, v in telemetry.calls.items() if k.startswith(stage + "/") and "/sql:" in k)
            == expected
        )
        assert (
            sum(
                v
                for k, v in telemetry.calls.items()
                if k.startswith(stage + "/") and k.endswith("new_pg_socket")
            )
            == 1
        )


@pytest.mark.parametrize(
    "mutation", ["index", "ready", "frontier", "observation", "segment", "count"]
)
def test_same_highwater_integrity_mutation_is_denied(source, postgres_dsn, mutation):
    stores, sid = source
    original = stores.tasks.read_stream_source_head(task_id=TaskId(sid))
    with psycopg.connect(postgres_dsn) as connection:
        if mutation == "index":
            connection.execute(
                "DELETE FROM task_event_index WHERE deployment_namespace=%s",
                (stores.deployment_namespace,),
            )
        elif mutation in {"ready", "frontier", "segment"}:
            assignment = {
                "ready": "event_position_source_ready=false",
                "frontier": "event_position_source_cursor=-1",
                "segment": "segment_index=1,predecessor_id=session_id",
            }[mutation]
            connection.execute(
                "UPDATE execution_segments SET " + assignment + " WHERE deployment_namespace=%s",
                (stores.deployment_namespace,),
            )
        elif mutation == "observation":
            connection.execute(
                "UPDATE session_observation_headers SET current_sequence=current_sequence+1 "
                "WHERE deployment_namespace=%s",
                (stores.deployment_namespace,),
            )
        else:
            connection.execute(
                "UPDATE agent_tasks SET next_event_sequence=next_event_sequence+1 "
                "WHERE deployment_namespace=%s",
                (stores.deployment_namespace,),
            )
    assert original is not None
    with pytest.raises((CheckpointConflict, CheckpointNotReady)):
        stores.tasks.read_stream_source_head(task_id=TaskId(sid))
    with pytest.raises((CheckpointConflict, CheckpointNotReady)):
        stores.tasks.read_stream_checkpoint_head(
            TaskId(sid), "legacy", ordinary_version="ag-ui-v1", coverage_version="ag-ui-v1-coverage"
        )


def test_same_highwater_status_is_fresh(source, postgres_dsn):
    stores, sid = source
    before = stores.tasks.read_stream_source_head(session_id=sid)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE session_observation_headers SET status='completed' "
            "WHERE deployment_namespace=%s",
            (stores.deployment_namespace,),
        )
    after = stores.tasks.read_stream_source_head(session_id=sid)
    assert before.session_sequence == after.session_sequence
    assert before.session_status != after.session_status


@pytest.mark.parametrize("marker", [None, {}, "malformed"])
def test_task_wide_privacy_and_namespace_are_source_owned(source, marker):
    stores, sid = source
    append(source, EventType.TASK_PREPARED, {"coverage_admission": marker})
    assert stores.tasks.read_stream_source_head(task_id=TaskId(sid)).task.strict_coverage
    captured = stores.tasks.read_stream_checkpoint_head(
        TaskId(sid), "legacy", ordinary_version="ag-ui-v1", coverage_version="ag-ui-v1-coverage"
    )
    run, head = captured.run, captured.head
    assert run.strict_coverage and head.scope.projector_version == "ag-ui-v1-coverage"
    assert stores.tasks.read_stream_source_head(task_id=TaskId(uuid4())) is None


@pytest.mark.parametrize("mutation", ["bytes", "header", "coordinate", "index_coordinate"])
def test_metadata_only_source_guards_cover_every_canonical_event(source, postgres_dsn, mutation):
    stores, sid = source
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("SET LOCAL session_replication_role=replica")
        if mutation == "index_coordinate":
            connection.execute(
                "UPDATE task_event_index SET segment_sequence=segment_sequence+100 "
                "WHERE deployment_namespace=%s",
                (stores.deployment_namespace,),
            )
        else:
            assignment = {
                "bytes": "event_bytes_bound=NULL",
                "header": "replay_header_ready=false",
                "coordinate": "task_sequence=task_sequence+100",
            }[mutation]
            connection.execute(
                "UPDATE session_events SET " + assignment + " WHERE deployment_namespace=%s",
                (stores.deployment_namespace,),
            )
    with pytest.raises((CheckpointConflict, CheckpointNotReady)):
        stores.tasks.read_stream_source_head(task_id=TaskId(sid))


def checkpoint_source(source):
    from agent_core.ports.task_projection_checkpoints import (
        ProjectionFrameHeader,
        ProjectionScope,
        ProjectionTransition,
    )

    stores, sid = source
    append(
        source, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}
    )
    run = stores.tasks.read_run_header(TaskId(sid), "run")
    scope = ProjectionScope(
        stores.deployment_namespace, TaskId(sid), run.anchor.event_id, "ag-ui-v1"
    )
    page = stores.tasks.read_event_page(TaskId(sid), -1)
    headers = tuple(
        ProjectionFrameHeader(
            entry.task_sequence,
            entry.event.event_id,
            entry.segment_id,
            entry.segment_sequence,
            -1,
            0,
            False,
            False,
        )
        for entry in page.events
    )
    stores.tasks.commit_projection_page(ProjectionTransition(scope, -1, headers, (), ()))
    return stores, sid, run, scope


@pytest.mark.parametrize("mutation", ["ahead", "last", "latest", "terminal", "frame_coordinate"])
def test_checkpoint_head_never_authorizes_corrupt_source_references(source, postgres_dsn, mutation):
    stores, sid, run, scope = checkpoint_source(source)
    captured = stores.tasks.read_stream_checkpoint_head(
        TaskId(sid), "run", ordinary_version="ag-ui-v1", coverage_version="ag-ui-v1-coverage"
    )
    before, head = captured.run, captured.head
    assert before == run and head.through_sequence == run.highwater
    with psycopg.connect(postgres_dsn) as connection:
        if mutation == "frame_coordinate":
            connection.execute(
                "UPDATE task_projection_heads SET latest_eligible_sequence=through_sequence "
                "WHERE deployment_namespace=%s AND projector_version='ag-ui-v1'",
                (stores.deployment_namespace,),
            )
            connection.execute(
                "UPDATE task_projection_frames SET segment_sequence=segment_sequence+100 "
                "WHERE deployment_namespace=%s",
                (stores.deployment_namespace,),
            )
        else:
            assignment = {
                "ahead": "through_sequence=through_sequence+1",
                "last": "last_event_id='00000000-0000-0000-0000-000000000001'",
                "latest": "latest_eligible_sequence=through_sequence",
                "terminal": "terminal_sequence=through_sequence",
            }[mutation]
            connection.execute(
                "UPDATE task_projection_heads SET " + assignment + " WHERE deployment_namespace=%s",
                (stores.deployment_namespace,),
            )
        if mutation == "latest":
            connection.execute(
                "DELETE FROM task_projection_frames WHERE deployment_namespace=%s",
                (stores.deployment_namespace,),
            )
    with pytest.raises((CheckpointConflict, CheckpointNotReady, ValueError)):
        stores.tasks.read_stream_checkpoint_head(
            TaskId(sid), "run", ordinary_version="ag-ui-v1", coverage_version="ag-ui-v1-coverage"
        )


def test_privacy_mutated_at_identical_frontier_is_requalified(source, postgres_dsn):
    stores, sid = source
    before = stores.tasks.read_stream_source_head(task_id=TaskId(sid))
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("SET LOCAL session_replication_role=replica")
        connection.execute(
            "UPDATE session_events SET event_type='task_prepared',"
            "payload='{" + '"coverage_admission":null' + "}'::jsonb "
            "WHERE deployment_namespace=%s AND sequence=0",
            (stores.deployment_namespace,),
        )
    after = stores.tasks.read_stream_source_head(task_id=TaskId(sid))
    assert before.task.current_sequence == after.task.current_sequence
    assert before.task.strict_coverage is False and after.task.strict_coverage is True


@pytest.mark.parametrize("case", ["pending", "control", "bound", "stop", "ambiguous"])
def test_run_selection_matches_existing_canonical_header(source, case):
    stores, sid = source
    if case != "pending":
        append(
            source,
            EventType.SESSION_COMMAND_ACCEPTED,
            {
                "kind": "cancel" if case == "control" else "run",
                "payload": {"run_id": "run"},
            },
        )
    if case in {"stop", "ambiguous"}:
        append(
            source,
            EventType.SESSION_COMMAND_ACCEPTED,
            {
                "kind": "run",
                "payload": {"run_id": "next" if case == "stop" else "run"},
            },
        )
    if case == "ambiguous":
        with pytest.raises(ValueError):
            stores.tasks.read_run_header(TaskId(sid), "run")
        with pytest.raises(ValueError):
            stores.tasks.read_stream_checkpoint_head(
                TaskId(sid),
                "run",
                ordinary_version="ag-ui-v1",
                coverage_version="ag-ui-v1-coverage",
            )
        return
    expected = stores.tasks.read_run_header(TaskId(sid), "run")
    captured = stores.tasks.read_stream_checkpoint_head(
        TaskId(sid), "run", ordinary_version="ag-ui-v1", coverage_version="ag-ui-v1-coverage"
    )
    run, head = captured.run, captured.head
    assert run == expected and head.scope.anchor_event_id == (
        run.anchor.event_id if run.anchor else None
    )


def test_bounded_membership_accepts_256_and_rejects_257(source, postgres_dsn):
    stores, sid = source
    namespace = stores.deployment_namespace
    base = stores.tasks.read_stream_source_head(task_id=TaskId(sid)).task.current_sequence + 1
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("SET LOCAL session_replication_role=replica")
        previous = sid
        for index in range(1, 256):
            member = uuid4()
            connection.execute(
                "INSERT INTO execution_segments (deployment_namespace,session_id,task_id,"
                "predecessor_id,segment_index,visibility,event_position_source_ready,"
                "event_position_source_cursor) VALUES (%s,%s,%s,%s,%s,'internal',true,0)",
                (namespace, member, sid, previous, index),
            )
            connection.execute(
                "INSERT INTO session_streams (deployment_namespace,session_id,current_version) "
                "VALUES (%s,%s,0)",
                (namespace, member),
            )
            event = uuid4()
            connection.execute(
                "INSERT INTO session_events (deployment_namespace,event_id,session_id,sequence,"
                "event_type,payload,actor,created_at,task_id,task_sequence,replay_header_ready,"
                "event_bytes_bound) VALUES (%s,%s,%s,0,'session_created','{}','harness',"
                "clock_timestamp(),%s,%s,true,100)",
                (namespace, event, member, sid, base + index - 1),
            )
            connection.execute(
                "INSERT INTO task_event_index (deployment_namespace,task_id,task_sequence,"
                "event_id,segment_id,segment_sequence) VALUES (%s,%s,%s,%s,%s,0)",
                (namespace, sid, base + index - 1, event, member),
            )
            previous = member
        connection.execute(
            "UPDATE agent_tasks SET next_event_sequence=next_event_sequence+255 "
            "WHERE deployment_namespace=%s",
            (namespace,),
        )
    assert stores.tasks.read_stream_source_head(task_id=TaskId(sid)) is not None
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("SET LOCAL session_replication_role=replica")
        connection.execute(
            "INSERT INTO execution_segments (deployment_namespace,session_id,task_id,"
            "predecessor_id,segment_index,visibility) VALUES (%s,%s,%s,%s,256,'internal')",
            (namespace, uuid4(), sid, previous),
        )
    with pytest.raises(CheckpointNotReady, match="bounded canonical prefix"):
        stores.tasks.read_stream_source_head(task_id=TaskId(sid))


def test_parent_head_and_durable_handoff_origin_are_independent_of_active_child(
    source,
    postgres_dsn,
    tmp_path,
):
    from tests.agent_storage.test_postgres_agent_tasks import _append_handoff_events, _seed_session

    stores, root = source
    child = _seed_session(postgres_dsn, stores.deployment_namespace, tmp_path / "child", "Child")
    _append_handoff_events(postgres_dsn, stores.deployment_namespace, root=root, child=child)
    stores.tasks.ensure_for_session(child)
    stores.tasks.backfill_replay_headers(TaskId(root))
    parent = stores.tasks.read_stream_source_head(session_id=root)
    current = stores.tasks.read_stream_source_head(task_id=TaskId(root))
    assert parent.task.active_segment_id == child
    assert parent.session_sequence == stores.events.read_session_highwater(root)
    assert parent.session_sequence < current.task.current_sequence
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("SET LOCAL session_replication_role=replica")
        connection.execute(
            "UPDATE session_events SET payload=jsonb_set(payload,'{root_session_id}',"
            "to_jsonb(%s::text)) WHERE deployment_namespace=%s "
            "AND event_type='session_handoff_received'",
            (str(uuid4()), stores.deployment_namespace),
        )
    with pytest.raises(CheckpointConflict, match="durable handoff origin"):
        stores.tasks.read_stream_source_head(session_id=root)


def test_event_checkpoint_snapshot_scope_lifetime_and_shared_metadata(source):
    from dataclasses import replace

    stores, sid, run, scope = checkpoint_source(source)
    telemetry = Telemetry()
    with telemetry.installed(), stores.tasks.read_checkpoint_snapshot(scope, run.start) as reader:
        connection = reader.connection
        head = reader.read_checkpoint_head(scope)
        frame = reader.read_event_projection_header(scope, run.start)
        assert head.scope == scope and frame.event_id == run.anchor.event_id
        assert reader.read_event_projection_header(scope, run.start) == frame
        with pytest.raises(CheckpointConflict):
            reader.read_checkpoint_head(replace(scope, projector_version="wrong-version"))
        with pytest.raises(CheckpointConflict):
            reader.read_cells_at(scope, run.start - 1, ())
        with pytest.raises(CheckpointConflict):
            reader.read_segment_checkpoint_before(scope, uuid4(), run.start)
    assert connection.closed
    with pytest.raises(CheckpointConflict):
        reader.read_checkpoint_head(scope)
    assert sum(v for k, v in telemetry.calls.items() if "/sql:" in k) == 5
    assert sum(v for k, v in telemetry.calls.items() if k.endswith("new_pg_socket")) == 1


def test_event_checkpoint_snapshot_rejects_oversized_cells_before_body_read(
    source, postgres_dsn, monkeypatch
):
    from agent_core.ports.task_projection_checkpoints import ProjectionCellKey
    from agent_storage.postgres.task_projection_checkpoint_rows import scope_values

    stores, sid, run, scope = checkpoint_source(source)
    keys = tuple(ProjectionCellKey(sid, "text_message", str(i) + "x" * 995) for i in range(60))
    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO task_projection_cells(deployment_namespace,task_id,anchor_key,"
                "projector_version,segment_id,cell_kind,cell_key,task_sequence,value,byte_count)"
                "VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s)",
                [
                    (
                        *scope_values(scope),
                        sid,
                        key.kind,
                        key.key,
                        "v" * 2048,
                        256 + 6 * len(key.key) + 6 * 2048,
                    )
                    for key in keys
                ],
            )
    execute = psycopg.Connection.execute

    def guard(connection, query, *args, **kwargs):
        if "cell.value" in str(query):
            pytest.fail("oversized restore hydrated checkpoint cell bodies")
        return execute(connection, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", guard)
    with pytest.raises(ValueError, match="byte bound"):
        with stores.tasks.read_checkpoint_snapshot(scope, run.start) as reader:
            connection = reader.connection
            reader.read_cells_at(scope, run.start, keys)
    assert connection.closed


def test_cached_event_checkpoint_reads_keep_deadline_and_integer_contract(source, monkeypatch):
    from agent_storage.postgres import task_projection_checkpoints as checkpoint_reads

    stores, _sid, _run, scope = checkpoint_source(source)
    with stores.tasks.read_checkpoint_snapshot(scope, 1) as reader:
        for invalid in (True, None):
            with pytest.raises(ValueError):
                reader.read_event_projection_header(scope, invalid)
        deadline = reader.deadline
        with monkeypatch.context() as clock:
            clock.setattr(checkpoint_reads, "monotonic", lambda: deadline + 0.001)
            with pytest.raises(TimeoutError):
                reader.read_checkpoint_head(scope)
            with pytest.raises(TimeoutError):
                reader.read_event_projection_header(scope, 1)


def test_actual_composed_head_run_seeks_and_restricted_role(
    source, postgres_dsn, monkeypatch, record_property, request
):
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.stream_source_head import read_checkpoint_source_head
    from psycopg import sql
    from psycopg.rows import dict_row

    stores, sid = source
    append(
        source, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "target"}}
    )
    namespace, count = stores.deployment_namespace, 100_000
    base = stores.events.read_session_highwater(sid) + 1
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("SET LOCAL session_replication_role=replica")
        connection.execute(
            "INSERT INTO session_events(deployment_namespace,event_id,session_id,"
            "sequence,event_type,"
            "actor,payload,created_at,task_id,task_sequence,event_bytes_bound,replay_header_ready,"
            "replay_command_kind,replay_run_id,replay_internal_continuation,"
            "projection_metadata_ready) "
            "SELECT %s,gen_random_uuid(),%s,n,'session_command_accepted','user',"
            '\'{"kind":"suspend","payload":{"run_id":"noise"}}\'::jsonb,now(),%s,n,1024,true,'
            "'suspend','noise',false,true FROM generate_series(%s::bigint,%s::bigint) n",
            (namespace, sid, sid, base, base + count - 1),
        )
        connection.execute(
            "INSERT INTO session_events(deployment_namespace,event_id,session_id,"
            "sequence,event_type,"
            "actor,payload,created_at,task_id,task_sequence,event_bytes_bound,replay_header_ready,"
            "replay_command_kind,replay_run_id,replay_internal_continuation,"
            "projection_metadata_ready) "
            "VALUES (%s,gen_random_uuid(),%s,%s,'session_command_accepted','user',"
            '\'{"kind":"run","payload":{"run_id":"next"}}\',now(),%s,%s,1024,true,\'run\','
            "'next',false,true),(%s,gen_random_uuid(),%s,%s,'model_response_delta','harness',"
            "jsonb_build_object('content_delta',repeat('x',8388608)),now(),%s,%s,8389376,true,"
            "NULL,NULL,false,true)",
            (
                namespace,
                sid,
                base + count,
                sid,
                base + count,
                namespace,
                sid,
                base + count + 1,
                sid,
                base + count + 1,
            ),
        )
        connection.execute(
            "INSERT INTO task_event_index(deployment_namespace,task_id,task_sequence,event_id,"
            "segment_id,segment_sequence) SELECT deployment_namespace,task_id,"
            "task_sequence,event_id,"
            "session_id,sequence FROM session_events WHERE deployment_namespace=%s "
            "AND session_id=%s "
            "AND sequence>=%s",
            (namespace, sid, base),
        )
        for query in (
            "UPDATE agent_tasks SET next_event_sequence=%s WHERE deployment_namespace=%s",
            "UPDATE execution_segments SET event_position_source_cursor=%s-1 WHERE "
            "deployment_namespace=%s",
            "UPDATE session_streams SET current_version=%s-1 WHERE deployment_namespace=%s",
            "UPDATE session_observation_headers SET current_sequence=%s-1 WHERE "
            "deployment_namespace=%s",
        ):
            connection.execute(query, (base + count + 2, namespace))
    captured = []
    execute = psycopg.Connection.execute

    def capture(connection, query, params=None, **kwargs):
        if str(query).startswith("SELECT to_jsonb(s) AS source"):
            captured.append((query, params))
        return execute(connection, query, params, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", capture)
    try:
        result = stores.tasks.read_stream_checkpoint_head(
            TaskId(sid), "target", ordinary_version="ag-ui-v1", coverage_version="ag-ui-v1-coverage"
        )
    except TimeoutError:
        record_property("bounded_api_head", "failclosed at unchanged2s deadline")
    else:
        assert result.run.stop == base + count
        record_property("bounded_api_head", "qualified within2s deadline")
    query, params = captured[0]
    import hashlib

    record_property("actual_composed_query_sha256", hashlib.sha256(query.encode()).hexdigest())
    role = "head_metadata_" + uuid4().hex
    role_created = False
    try:
        with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            record_property("postgres_server_version", connection.info.server_version)
            plan = connection.execute(
                "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + query, params
            ).fetchone()["QUERY PLAN"][0]
        import json

        artifact = Path(request.config.getoption("xmlpath")).parent / "actual-composed-plan.json"
        artifact.write_text(json.dumps(plan, indent=2) + "\n")
        artifact.chmod(0o600)
        record_property("actual_composed_plan_file", artifact.name)
        nodes, source_nodes = [], []

        def walk(node, parent="", in_run=False):
            owner = node.get("Subplan Name", parent)
            in_run = in_run or node.get("Alias") == "r"
            index = node.get("Index Name", "")
            run_seek = "scalar_executable" in index or "scalar_command" in index
            if run_seek or any(name in owner for name in ("CTE executable", "CTE stop_position")):
                nodes.append(
                    {
                        key: node.get(key)
                        for key in (
                            "Node Type",
                            "Relation Name",
                            "Index Name",
                            "Actual Rows",
                            "Actual Loops",
                            "Actual Total Time",
                            "Rows Removed by Filter",
                            "Subplan Name",
                        )
                    }
                )
                if node.get("Relation Name") == "session_events":
                    assert node["Actual Rows"] + node.get("Rows Removed by Filter", 0) <= 2
            elif node.get("Relation Name") in {"session_events", "task_event_index"} or node.get(
                "Node Type"
            ) in {"Aggregate", "WindowAgg", "Sort", "Incremental Sort"}:
                source_nodes.append(
                    {
                        key: node.get(key)
                        for key in (
                            "Node Type",
                            "Relation Name",
                            "Index Name",
                            "Actual Rows",
                            "Actual Loops",
                            "Actual Total Time",
                            "Sort Method",
                            "Sort Space Used",
                            "Sort Space Type",
                            "Temp Read Blocks",
                            "Temp Written Blocks",
                            "Rows Removed by Filter",
                        )
                    }
                )
            for child in node.get("Plans", []):
                walk(child, owner, in_run)

        walk(plan["Plan"])
        assert nodes
        record_property("actual_composed_run_plan", nodes)
        record_property("source_or_other_plan_nodes", source_nodes)
        record_property("actual_composed_execution_ms", plan["Execution Time"])
        record_property("source_history_rows", base + count + 2)
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
            role_created = True
            connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role))
            )
            connection.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(
                    sql.Identifier(role)
                )
            )
            connection.execute(
                sql.SQL("REVOKE SELECT ON session_events FROM {}").format(sql.Identifier(role))
            )
            columns = connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE "
                "table_schema='public' AND table_name='session_events' AND column_name<>'payload'"
            ).fetchall()
            connection.execute(
                sql.SQL("GRANT SELECT ({}) ON session_events TO {}").format(
                    sql.SQL(",").join(sql.Identifier(row[0]) for row in columns),
                    sql.Identifier(role),
                )
            )
        with PostgresDatabase(
            postgres_dsn, deployment_namespace=namespace
        ).connect_task_io() as connection:
            connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                read_checkpoint_source_head(
                    connection,
                    namespace,
                    TaskId(sid),
                    "target",
                    ordinary_version="ag-ui-v1",
                    coverage_version="ag-ui-v1-coverage",
                )
        record_property("actual_composed_no_payload_role", "failclosed InsufficientPrivilege")
    finally:
        if role_created:
            with psycopg.connect(postgres_dsn) as connection:
                connection.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
