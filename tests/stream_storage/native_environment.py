"""Own one disposable database and Redis prefix; reuse catalog and native seams."""

from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import TaskId
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_integrations.redis_live_fanout import RedisCommittedEventPublisher, RedisLiveEventFanout
from agent_storage import (
    PostgresAgentTaskStore,
    PostgresEventStore,
    PostgresLeaseStore,
    PostgresModelToolProjectionStore,
    PostgresProjectionStore,
    PostgresWorkspaceProjectionStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from agent_storage.live_event_store import with_worker_projection_publisher
from agent_storage.postgres.worker_replay_reader import PostgresWorkerReplayReader
from agent_storage.postgres_model_tool_compat import (
    PostgresModelCallProjectionAdapter,
    PostgresToolRunProjectionAdapter,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from redis import Redis
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.tool_run_index import ToolRunIndexer

from tests.agent_integrations.binding_store_cases import publish, ready, resolve, scope_for
from tests.stream_storage.telemetry import phase


@contextmanager
def native_environment(configured, redis_url):
    settings = conninfo_to_dict(configured)
    if settings.get("host") not in {"127.0.0.1", "localhost"}:
        raise ValueError("baseline requires a disposable local PostgreSQL endpoint")
    name = f"zebra_stream_{uuid4().hex}"
    admin_dsn = make_conninfo(configured, dbname="postgres")
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    prefix = f"zebra:baseline:{uuid4().hex}"
    client = None
    try:
        client = Redis.from_url(redis_url, socket_timeout=2, socket_connect_timeout=2)
        client.ping()
        dsn = make_conninfo(configured, dbname=name)
        apply_postgres_migrations(dsn)
        with psycopg.connect(dsn) as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
        fanout = RedisLiveEventFanout(client, key_prefix=prefix, max_stream_length=100_000)
        yield dsn, client, fanout
    finally:
        # Delete exactly this run's prefix, never FLUSHDB or business namespaces.
        try:
            if client is not None:
                for key in client.scan_iter(match=f"{prefix}:*"):
                    client.delete(key)
        finally:
            if client is not None:
                client.close()
            with psycopg.connect(admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def seed(dsn, fanout, seconds):
    namespace = f"stream-baseline-{uuid4().hex}"
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    events = PostgresEventStore(dsn, deployment_namespace=namespace)
    sessions = PostgresProjectionStore(dsn, deployment_namespace=namespace)
    workspaces = PostgresWorkspaceProjectionStore(dsn, deployment_namespace=namespace)
    tasks = PostgresAgentTaskStore(dsn, deployment_namespace=namespace)
    indexes = PostgresModelToolProjectionStore(dsn, deployment_namespace=namespace)
    # Same real adapters as cloud composition; unused artifact/memory ports are absent.
    stores = SimpleNamespace(
        events=events,
        sessions=sessions,
        tasks=tasks,
        workspaces=workspaces,
        deployment_namespace=namespace,
        namespace=namespace,
        projection_work=None,
        coverage_projection_work=None,
    )
    boot = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Synthetic native stream baseline",
            user_input="Synthetic input",
            workspace_root=Path("/tmp/zebra-stream-baseline"),
        )
    )
    for event in boot.events:
        events.append(event)
    sessions.save_session(boot.session)
    workspace = rebuild_workspace(list(boot.events))
    workspaces.save_workspace(workspace)
    task = tasks.ensure_for_session(boot.session.session_id)
    lease = PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        boot.session.session_id,
        owner_instance_id="native-baseline",
        ttl=timedelta(seconds=max(300, seconds * 3 + 30)),
    )
    publisher = RedisCommittedEventPublisher(fanout, deployment_namespace=namespace)
    recorder = DurableHarnessEventRecorder(
        session=boot.session,
        workspace=workspace,
        event_store=events,
        projection_store=sessions,
        workspace_store=workspaces,
        model_call_indexer=ModelCallIndexer(PostgresModelCallProjectionAdapter(indexes)),
        tool_run_indexer=ToolRunIndexer(PostgresToolRunProjectionAdapter(indexes)),
        worker_projection_transaction=with_worker_projection_publisher(workspaces, publisher),
        worker_mutation_authority=WorkerMutationAuthority(
            deployment_namespace=namespace,
            session_id=boot.session.session_id,
            lease_fence=lease.fence,
            expected_stream_revision=boot.session.current_sequence,
        ),
        tail_reader=PostgresWorkerReplayReader(dsn, deployment_namespace=namespace).tail_page,
    )
    command = SessionCommand(
        session_id=boot.session.session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=recorder.session.current_sequence,
        idempotency_key=uuid4().hex,
        payload={"run_id": "run"},
    )
    recorder.append(EventType.SESSION_COMMAND_ACCEPTED, EventActor.USER, command.event_payload())
    recorder.append(EventType.HARNESS_ATTEMPT_STARTED, EventActor.HARNESS, {"attempt_number": 1})
    materialize(stores, task.task_id)
    return SimpleNamespace(
        stores=stores,
        recorder=recorder,
        task_id=task.task_id,
        session_id=boot.session.session_id,
        namespace=namespace,
        model_call_id=str(uuid4()),
    )


def materialize(stores, task_id: TaskId):
    with phase("writer/checkpoint"):
        run = ready(stores.tasks, task_id)
        scope = scope_for(stores, run)
        resolve(stores.tasks, run, scope)
        publish(stores.tasks, run, scope)
