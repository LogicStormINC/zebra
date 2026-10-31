"""Run only in the disposable no-production-network PostgreSQL scratch deployment."""

import ast
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NSValue
from uuid import uuid4

import psycopg
from agent_core.domain.identifiers import TaskId
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.migrations import MIGRATIONS
from agent_storage.postgres.projection_work import PostgresTaskProjectionWorkStore

DSN = "postgresql://postgres@qa-pg/stability_scratch"
NS = "erpnext"
with psycopg.connect(DSN) as c:
    assert c.execute("select current_database()").fetchone()[0] == "stability_scratch"
    for migration in sorted(MIGRATIONS, key=lambda m: m.version):
        if migration.version <= 105:
            for statement in migration.statements:
                c.execute(statement)
print("PASS isolated native105 schema initialized", flush=True)


def seed():
    task = uuid4()
    with psycopg.connect(DSN) as c:
        c.execute("INSERT INTO session_streams VALUES (%s,%s,0)", (NS, task))
        c.execute(
            (
                "INSERT INTO session_projections (deployment_namespace,session_id"
                ",title,status,created_at,updated_at,current_sequence) VALUES (%s"
                ",%s,'owned QA','created',now(),now(),0)"
            ),
            (NS, task),
        )
        c.execute(
            (
                "INSERT INTO agent_tasks(deployment_namespace,task_id,root_sessio"
                "n_id,active_segment_id,created_at,updated_at,next_event_sequence"
                ",event_position_state) VALUES (%s,%s,%s,%s,now(),now(),0,'ready'"
                ")"
            ),
            (NS, task, task, task),
        )
        c.execute(
            (
                "INSERT INTO execution_segments(deployment_namespace,session_id,t"
                "ask_id,segment_index,visibility,event_position_source_cursor,eve"
                "nt_position_source_ready) VALUES (%s,%s,%s,0,'internal',-1,true)"
            ),
            (NS, task, task),
        )
    return TaskId(task)


store = PostgresTaskProjectionWorkStore(PostgresDatabase(DSN, deployment_namespace=NS), "ag-ui-v1")
store.enable_projection_work()
task = seed()
assert not store.repair_projection_work(task).needs_repair
assert store.read_projection_work_repairs() == ()


def append(n):
    with psycopg.connect(DSN) as c:
        c.execute("SET LOCAL lock_timeout='50ms'")
        c.execute(
            (
                "INSERT INTO session_events(deployment_namespace,event_id,session"
                "_id,sequence,event_type,payload,actor,created_at) VALUES (%s,%s,"
                "%s,%s,'session_title_updated','{\"title\":\"QA\"}','system',now())"
            ),
            (NS, uuid4(), task, n),
        )
        c.commit()  # Actual native deferred allocation and route trigger.


held, release = threading.Event(), threading.Event()
original = store._connect


@contextmanager
def hold_healthy_repair(**kwargs):
    with original(**kwargs) as connection:
        yield connection
        held.set()
        assert release.wait(3)


store._connect = hold_healthy_repair
errors = []


def repairing():
    try:
        store.repair_projection_work(task)
    except Exception as error:
        errors.append(type(error).__name__)


thread = threading.Thread(target=repairing)
thread.start()
assert held.wait(3)
try:
    try:
        append(0)
    except psycopg.errors.LockNotAvailable:
        print(
            "PASS reproduced actual healthy repair blocking native event COMMIT at50ms", flush=True
        )
    else:
        raise AssertionError("old repair did not reproduce conflict")
finally:
    release.set()
    thread.join()
    store._connect = original
assert not errors, errors
# Candidate queue dispatch does not call repair for this already-converged Task.
for n in range(100):
    assert store.read_projection_work_repairs() == ()
    append(n)
assert store.read_projection_work_repairs() == ()
print(
    json.dumps(
        {
            "native_appends_without_unnecessary_repair": 100,
            "lock_failures": 0,
            "production_connections": 0,
        }
    ),
    flush=True,
)

# Run the actual candidate loop concurrently with native appends in this isolated
# DB. Only the synthetic eligibility gate is substituted; no authority claim.

task_version = __import__(
    "agent_storage.projection_work_routing", fromlist=("task_version",)
).task_version

fn = next(
    n
    for n in ast.parse(Path("/tmp/candidate.py").read_text()).body
    if isinstance(n, ast.FunctionDef) and n.name == "run_chat_projection"
)
fn.body = [n for n in fn.body if not isinstance(n, ast.ImportFrom)]
stop = threading.Event()
calls = {"repair": 0, "poll": 0}
original_repair = store.repair_projection_work
original_pending = store.read_pending_projection_work


def unexpected_repair(*args, **kwargs):
    calls["repair"] += 1
    raise AssertionError("healthy Task entered repair")


def pending(*args, **kwargs):
    calls["poll"] += 1
    return original_pending(*args, **kwargs)


store.repair_projection_work = unexpected_repair
store.read_pending_projection_work = pending
coverage = PostgresTaskProjectionWorkStore(
    PostgresDatabase(DSN, deployment_namespace=NS), "ag-ui-v1-coverage"
)
policy = NSValue(
    _database=PostgresDatabase(DSN, deployment_namespace=NS), require=lambda session: None
)
consumer = NSValue(work=store, materialize_once=lambda work: None)
other = NSValue(work=coverage, materialize_once=lambda work: None)
loop = NSValue(
    _execution_service=NSValue(_erp_workspace_containment=policy),
    _projection_work=NSValue(consumers=[consumer, other]),
)
scope = {
    "candidate_sql": lambda alias: " AND t.task_id='" + str(task) + "'::uuid",
    "task_version": task_version,
}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "candidate.py", "exec"), scope)
thread = threading.Thread(target=scope["run_chat_projection"], args=(loop, stop))
thread.start()
try:
    for n in range(100, 200):
        append(n)
        time.sleep(0.02)
finally:
    stop.set()
    thread.join()
assert calls["repair"] == 0, calls
assert calls["poll"] >= 2, calls
print(
    json.dumps(
        {
            "candidate_loop_concurrent_native_appends": 100,
            "healthy_repairs": 0,
            "loop_polls": calls["poll"],
            "synthetic_eligibility_gate": True,
        }
    ),
    flush=True,
)
