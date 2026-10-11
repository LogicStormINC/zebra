"""Real cloud PG composition and read-only SQL observation in isolated schemas."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Generator
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.host_authority import HostSessionGrant
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import ProjectionScope
from agent_integrations.ag_ui.checkpoint_plan import AG_UI_CHECKPOINT_VERSION
from agent_security.host_grant import (
    HostGrantVerificationConfig,
    HostGrantVerifier,
    JwtAlgorithm,
    VerifiedHostGrant,
)
from agent_storage import (
    CloudCompositionSettings,
    ControlPlaneStores,
    PostgresControlPlaneStores,
    apply_postgres_migrations,
    postgres_control_plane_stores,
)
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from zebra_agent_api import http


@dataclass(frozen=True)
class PgGetReplay:
    dsn: str = field(repr=False)
    readonly_dsn: str = field(repr=False)
    session: SessionId
    cloud: CloudCompositionSettings = field(repr=False)
    verified: VerifiedHostGrant
    path: Path

    def stores(self, *, readonly: bool = False) -> PostgresControlPlaneStores:
        return postgres_control_plane_stores(
            self.readonly_dsn if readonly else self.dsn,
            deployment_namespace=self.cloud.deployment_namespace,
            memory_cursor_signing_key=self.cloud.memory_cursor_signing_key,
            artifact_objects=self.cloud.artifact_objects,
            history_scope=self.cloud.history_scope,
            continuation_scope=self.cloud.continuation_scope,
        )

    def prepare_run(self, *, stopped: bool = False, prefix: int = 0) -> None:
        from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
        from agent_core.domain.events import EventActor, EventType, SessionEvent

        from tests.api.ag_ui_checkpoint_fixture import prepare_checkpoint

        stores = self.stores()
        session = stores.sessions.get_session(self.session)
        assert session is not None
        assert not (stopped and prefix)
        kinds = [EventType.SESSION_COMMAND_ACCEPTED]
        kinds.extend([EventType.MODEL_RESPONSE_RECEIVED] * (prefix + 1 if prefix else 2))
        if not prefix:
            kinds.append(
                EventType.SESSION_COMMAND_ACCEPTED if stopped else EventType.SESSION_COMPLETED
            )
        if stopped:
            kinds.extend([EventType.MODEL_RESPONSE_RECEIVED, EventType.SESSION_COMPLETED])
        for offset, kind in enumerate(kinds, session.current_sequence + 1):
            payload: dict[str, object]
            if kind == EventType.SESSION_COMMAND_ACCEPTED:
                run_id = "run-1" if offset == session.current_sequence + 1 else "run-2"
                payload = SessionCommand(
                    session_id=self.session,
                    kind=SessionCommandKind.RUN,
                    expected_revision=offset,
                    idempotency_key=f"pg-{run_id}",
                    payload={"run_id": run_id},
                ).event_payload()
            elif kind == EventType.MODEL_RESPONSE_RECEIVED:
                payload = {
                    "model_call_id": f"model-{offset}",
                    "assistant_message": f"pg-answer-{offset}",
                }
            else:
                payload = {}
            stores.events.append(
                SessionEvent.create(
                    session_id=self.session,
                    sequence=offset,
                    event_type=kind,
                    actor=EventActor.HARNESS,
                    payload=payload,
                )
            )
        for run_id in ["run-1", "run-2"] if stopped else ["run-1"]:
            prepare_checkpoint(
                cast(ControlPlaneStores, stores),
                self.session,
                run_id,
                namespace=self.cloud.deployment_namespace,
                through_sequence=offset - 1 if prefix else None,
            )

    def client(self, grant: VerifiedHostGrant | None = None) -> TestClient:
        from tests.api.test_extension_reads import Authorizer
        from tests.api.test_postgres_host_auth_authorizer import _settings

        return TestClient(
            http.create_http_app(
                self.path,
                settings=_settings(self.readonly_dsn),
                cloud_composition=replace(self.cloud, dsn=self.readonly_dsn),
                host_grant_authorizer=Authorizer(grant or self.verified),
            )
        )

    def prepare_problem(
        self,
        code: str,
        *,
        attempts: int = 1,
        retry_after: float | None = None,
    ) -> ProjectionScope:
        """Real producer/queue maintenance outside GET, with a >256 dense prefix."""
        self.prepare_run(prefix=260)
        stores = self.stores()
        task_id = TaskId(self.session)
        run = stores.tasks.read_run_header(task_id, "run-1")
        assert run.anchor is not None
        scope = ProjectionScope(
            self.cloud.deployment_namespace,
            task_id,
            run.anchor.event_id,
            AG_UI_CHECKPOINT_VERSION,
        )
        head = stores.tasks.read_checkpoint_head(scope)
        assert head.through_sequence == run.highwater - 1 and head.through_sequence >= 256
        work = stores.projection_work
        assert work is not None
        work.enable_projection_work()
        assert work.bootstrap_projection_work(limit=32)
        while work.repair_projection_work(task_id, limit=256).needs_repair:
            pass
        for attempt in range(1, attempts + 1):
            (pending,) = work.read_pending_projection_work(limit=32)
            assert pending.scope == scope and pending.after_sequence == head.through_sequence
            assert work.defer_projection_work(
                pending, problem_code=code, retry_after_seconds=retry_after
            )
            if attempt < attempts:
                assert work.retry_projection_work(scope, expected_attempt=attempt)
        problem = work.read_projection_work_problem(scope)
        assert problem is not None and problem.scope == scope
        assert problem.code == code
        assert problem.attempts == (0 if code == "not_ready" and retry_after is None else attempts)
        assert (problem.retry_at is not None) == (retry_after is not None)
        return scope


@pytest.fixture
def pg_get_replay(tmp_path: Path) -> Generator[PgGetReplay]:
    """Opt-in real cloud PG probe; fail rather than skip if scratch authority is absent."""
    from agent_storage.postgres.task_admission import save_task_binding
    from zebra_agent_api.session_binding import _build_binding_snapshot

    from tests.api.test_postgres_host_auth_authorizer import _claims, _registry
    from tests.test_cloud_api_worker_profile_composition import _cloud_settings

    configured = os.environ.get("ZEBRA_HEADER_SCRATCH_DSN")
    assert configured, "explicit PG GET probe requires ZEBRA_HEADER_SCRATCH_DSN"
    settings = conninfo_to_dict(configured)
    assert settings.get("dbname") == "header_scratch"
    assert settings.get("host") in {"127.0.0.1", "localhost"}
    assert settings.get("port") == "32786"
    schema = f"api_get_{uuid4().hex}"
    with psycopg.connect(configured) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(configured, options=f"-c search_path={schema}")
    readonly = make_conninfo(
        configured, options=f"-c search_path={schema} -c default_transaction_read_only=on"
    )
    try:
        apply_postgres_migrations(dsn)
        registry = _registry()
        claims = _claims(f"get-{uuid4().hex}")
        claims["resource_refs"] = [
            {"type": "principal", "id": "get-quality-user"},
            {"type": "thread", "id": f"Trench:opaque/get-quality-{uuid4().hex}"},
        ]
        verified = HostGrantVerifier(
            HostGrantVerificationConfig(
                issuer=registry.issuer,
                audience=registry.audience,
                jwks_uri=registry.jwks_uri,
                allowed_origins=registry.allowed_origins,
            )
        ).verify(
            HostSessionGrant.model_validate(claims),
            algorithm=JwtAlgorithm.RS256,
            now=datetime.now(UTC),
        )
        cloud = replace(_cloud_settings(), dsn=dsn, deployment_namespace="get-quality-pg")
        stores = postgres_control_plane_stores(
            dsn,
            deployment_namespace=cloud.deployment_namespace,
            memory_cursor_signing_key=cloud.memory_cursor_signing_key,
            artifact_objects=cloud.artifact_objects,
            history_scope=cloud.history_scope,
            continuation_scope=cloud.continuation_scope,
        )
        bootstrap = SessionBootstrapService().build(
            SessionBootstrapCommand(
                title="Cloud GET quality",
                user_input="Replay the durable stream.",
                workspace_root=tmp_path,
                host_context=verified.context,
            )
        )
        for event in bootstrap.events:
            stores.events.append(event)
        stores.sessions.save_session(bootstrap.session)
        stores.workspaces.save_workspace(rebuild_workspace(list(bootstrap.events)))
        binding = _build_binding_snapshot(
            bootstrap.session.session_id,
            host_context=verified.context,
            definition_snapshot_digest=None,
            verified_host_grant=verified,
        )
        save_task_binding(dsn, deployment_namespace=cloud.deployment_namespace, binding=binding)
        yield PgGetReplay(dsn, readonly, bootstrap.session.session_id, cloud, verified, tmp_path)
    finally:
        # Only the generated schema is removed. Container/database/public schema are untouched.
        with psycopg.connect(configured) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


class PgSqlObservation:
    """Record attempted SQL; PG read-only transactions independently reject any DML."""

    COMMAND_ID_POINT = (
        "SELECT event_id,session_id,sequence,event_type,actor,created_at, "
        "payload->>'command_id' AS command_id FROM session_events "
        "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence=%s "
        "AND event_id=%s AND session_id=%s AND sequence=%s"
    )

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.writes: list[str] = []
        self.body_reads: list[str] = []
        self.body_limits: list[int] = []
        self.body_connections: list[str] = []
        self.rejected_body_reads: list[str] = []
        self.connections: set[str] = set()
        self.command_points: list[tuple[object, ...]] = []
        self.command_connections: list[str] = []
        self.bodies = False
        execute = psycopg.Cursor.execute

        def observed_execute(
            cursor: psycopg.Cursor[Any],
            query: Any,
            params: Any = None,
            **kwargs: Any,
        ) -> psycopg.Cursor[Any]:
            self.connections.add(type(cursor.connection).__name__)
            statement = " ".join(
                (
                    query.as_string(cursor.connection)
                    if isinstance(query, sql.Composable)
                    else str(query)
                ).split()
            )
            if re.search(
                r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|COPY|TRUNCATE)\b",
                statement,
                re.IGNORECASE,
            ) or re.search(r"\bFOR (UPDATE|SHARE)\b", statement, re.IGNORECASE):
                self.writes.append(statement)
            if statement == self.COMMAND_ID_POINT:
                assert len(params) == 6 and isinstance(params[0], str)
                assert all(isinstance(params[index], UUID) for index in (1, 3, 4))
                assert all(type(params[index]) is int and params[index] >= 0 for index in (2, 5))
                self.command_points.append(tuple(params))
                self.command_connections.append(type(cursor.connection).__name__)
                return execute(cursor, query, params, **kwargs)
            if "session_events" in statement and re.search(
                r"\bpayload\b|SELECT (?:event\.)?\*",
                statement,
                re.IGNORECASE,
            ):
                self.body_reads.append(statement)
                self.body_connections.append(type(cursor.connection).__name__)
                try:
                    assert self.bodies, "PG preflight hydrated an Event body"
                    assert "event.task_sequence>%s" in statement
                    assert "event.task_sequence<=%s" in statement
                    assert "ORDER BY event.task_sequence LIMIT %s" in statement
                    assert 1 <= params[-1] <= 256
                except AssertionError:
                    self.rejected_body_reads.append(statement)
                    raise
                self.body_limits.append(params[-1])
            return execute(cursor, query, params, **kwargs)

        # ClientCursor inherits this execute method; native connection creation is untouched.
        monkeypatch.setattr(psycopg.Cursor, "execute", observed_execute)


def pg_rows(dsn: str) -> dict[str, str]:
    """Fingerprint every tiny scratch table outside GET, without logging row bodies."""
    with psycopg.connect(dsn) as connection:
        tables = connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema=current_schema() AND table_type='BASE TABLE'"
        ).fetchall()
        fingerprints: dict[str, str] = {}
        for (table,) in tables:
            row = connection.execute(
                sql.SQL(
                    "SELECT md5(COALESCE(string_agg(row_to_json(t)::text, '\n' "
                    "ORDER BY row_to_json(t)::text),'')) FROM {} t"
                ).format(sql.Identifier(table))
            ).fetchone()
            assert row is not None and isinstance(row[0], str)
            fingerprints[table] = row[0]
        return fingerprints


@pytest.mark.parametrize("client_cursor", [False, True])
def test_sql_observation_covers_real_native_task_io_connection(
    pg_get_replay: PgGetReplay,
    monkeypatch: pytest.MonkeyPatch,
    client_cursor: bool,
) -> None:
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.task_io import TaskIoConnection

    replay = pg_get_replay
    database = PostgresDatabase(
        replay.readonly_dsn,
        deployment_namespace=replay.cloud.deployment_namespace,
    )
    before = pg_rows(replay.dsn)
    with monkeypatch.context() as patch:
        observed = PgSqlObservation(patch)
        with database.connect_task_io(timeout_seconds=1, client_cursor=client_cursor) as connection:
            assert isinstance(connection, TaskIoConnection)
            row = connection.execute("SELECT 1 AS observed").fetchone()
            assert row is not None and row["observed"] == 1
            point = (
                replay.cloud.deployment_namespace,
                replay.session,
                0,
                uuid4(),
                replay.session,
                0,
            )
            assert connection.execute(PgSqlObservation.COMMAND_ID_POINT, point).fetchone() is None
            observed.bodies = True  # Raw bodies remain forbidden outside a bounded Page, too.
            for query in (
                "SELECT event.payload FROM session_events event LIMIT 1",
                "SELECT event.* FROM session_events event LIMIT 1",
                "SELECT payload->>'command_id' FROM session_events LIMIT 1",
            ):
                with pytest.raises(AssertionError):
                    connection.execute(query)
        assert connection.closed and observed.connections == {"TaskIoConnection"}
        assert observed.writes == [] and len(observed.body_reads) == 3
        assert observed.body_limits == []  # Rejected before the real driver can hydrate a body.
        assert len(observed.rejected_body_reads) == 3 and observed.command_points == [point]
    assert pg_rows(replay.dsn) == before


@pytest.mark.parametrize("stage", ["snapshot", "cursor", "page", "frame", "problem", "outcome"])
def test_cloud_pg_tail_read_shares_grant_deadline_and_cleans_native_query(
    pg_get_replay: PgGetReplay,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    from agent_integrations.ag_ui import AgUiCursor, AgUiRunIdentity
    from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
    from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
    from agent_storage.postgres.command_wakeup_outcome import PostgresCommandOutcomeReader
    from agent_storage.postgres.projection_work import PostgresTaskProjectionWorkStore
    from agent_storage.postgres.task_io import TaskIoConnection
    from zebra_agent_api import ag_ui_stream

    from tests.api.test_extension_reads import AUTH

    replay = pg_get_replay
    replay.prepare_run(prefix=1)  # One materialized model Event, one outstanding source Event.
    stores = replay.stores()
    task_id = TaskId(replay.session)
    run = stores.tasks.read_run_header(task_id, "run-1")
    assert run.anchor is not None
    cursor = AgUiCursor(
        thread_id=str(task_id),
        run_id="run-1",
        sequence=run.anchor.task_sequence,
        event_id=str(run.anchor.event_id),
    )
    prefix = "".join(
        frame
        for _, frame in ag_ui_stream._project_new_task_events(
            stores.tasks.read_events(task_id, -1)[:-1],
            AgUiRunIdentity(session_id=replay.session, thread_id=str(task_id), run_id="run-1"),
            cursor,
        )
    )
    assert prefix.count("id: ") == 3
    before = pg_rows(replay.dsn)
    client = replay.client()
    targets: dict[str, tuple[type[Any], str]] = {
        "snapshot": (AgUiCheckpointObserver, "snapshot"),
        "cursor": (AgUiCheckpointObserver, "validate_cursor"),
        "page": (AgUiCheckpointObserver, "read_page"),
        "frame": (PostgresAgentTaskStore, "read_event_projection_header"),
        "problem": (PostgresTaskProjectionWorkStore, "read_projection_work_problem"),
        "outcome": (PostgresCommandOutcomeReader, "__call__"),
    }
    owner, method = targets[stage]
    read: Callable[..., Any] = getattr(owner, method)
    active: ContextVar[bool] = ContextVar("faulted_tail_read", default=False)
    prepare = ag_ui_stream.prepare_agui_stream
    execute = psycopg.Cursor.execute
    finished = Event()
    connections: list[TaskIoConnection] = []
    armed, stream_deadline = False, 0.0
    backend_pid = 0
    with monkeypatch.context() as patch:
        observed = PgSqlObservation(patch)
        observed_execute = psycopg.Cursor.execute

        def preflight(*args: Any, **kwargs: Any) -> Any:
            nonlocal armed, stream_deadline
            context = prepare(*args, **kwargs)
            assert isinstance(context, ag_ui_stream.AgUiStreamContext)
            assert observed.body_reads == []
            # Reduce, never extend, the authorized lifetime after real scoped preflight.
            stream_deadline = monotonic() + 0.45
            armed = observed.bodies = True
            return replace(
                context, authorization_expires_at=datetime.now(UTC) + timedelta(seconds=0.45)
            )

        def scoped_read(*args: Any, **kwargs: Any) -> Any:
            token = active.set(armed)
            try:
                return read(*args, **kwargs)
            finally:
                active.reset(token)
                if connections:
                    finished.set()

        def stalled_execute(
            sql_cursor: psycopg.Cursor[Any], query: Any, params: Any = None, **kwargs: Any
        ) -> psycopg.Cursor[Any]:
            nonlocal backend_pid
            connection = sql_cursor.connection
            if active.get() and not connections and isinstance(connection, TaskIoConnection):
                connections.append(connection)
                backend_pid = connection.info.backend_pid
                # Real libpq query on the actual composition's native connection, not a sleep mock.
                execute(sql_cursor, "SELECT pg_sleep(5)")
            return observed_execute(sql_cursor, query, params, **kwargs)

        patch.setattr(http, "prepare_agui_stream", preflight)
        patch.setattr(owner, method, scoped_read)
        patch.setattr(psycopg.Cursor, "execute", stalled_execute)
        response = client.get(
            f"/agui/threads/{replay.session}/runs/run-1/stream",
            headers=AUTH,
            params={"cursor": cursor.encode()},
        )
        assert response.status_code == 200
        assert response.text == (prefix if stage in {"problem", "outcome"} else "")
        assert len(connections) == 1 and finished.wait(0.15)
        assert connections[0].closed  # Socket closure, not just coroutine cancellation.
        assert connections[0].deadline <= stream_deadline + 0.02
        assert monotonic() <= stream_deadline + 0.15
        assert observed.writes == [] and observed.rejected_body_reads == []
        assert set(observed.body_connections) <= {"TaskIoConnection"}
        print(f"{stage}: native query closed within the 450ms stream budget; no late frame")
    cleanup_deadline = monotonic() + 0.3
    with psycopg.connect(replay.readonly_dsn, autocommit=True) as connection:
        while connection.execute(
            "SELECT 1 FROM pg_stat_activity WHERE pid=%s", (backend_pid,)
        ).fetchone():
            assert monotonic() < cleanup_deadline, "expired tail query retained its backend"
            sleep(0.01)
    assert pg_rows(replay.dsn) == before


def test_native_tail_read_cumulative_budget_and_scope_restore(
    pg_get_replay: PgGetReplay,
) -> None:
    import asyncio
    from threading import get_ident

    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.task_io import TaskIoConnection
    from zebra_agent_api.ag_ui_checkpoint_tail import _read_until

    replay = pg_get_replay
    database = PostgresDatabase(
        replay.readonly_dsn, deployment_namespace=replay.cloud.deployment_namespace
    )
    before = pg_rows(replay.dsn)
    connections: list[TaskIoConnection] = []

    async def check() -> None:
        loop_thread = get_ident()
        ticks = 0

        async def tick() -> None:
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.02)

        def paired_read() -> None:
            assert get_ident() != loop_thread
            for delay in (0.9, 5):
                with database.connect_task_io() as connection:
                    assert isinstance(connection, TaskIoConnection)
                    connections.append(connection)
                    connection.execute("SELECT pg_sleep(%s)", (delay,))

        started = monotonic()
        ticker = asyncio.create_task(tick())
        try:
            # A long-lived stream does not grant each connection a fresh two seconds.
            with pytest.raises((TimeoutError, psycopg.errors.QueryCanceled)):
                await _read_until(started + 30, paired_read)
            assert monotonic() - started <= 2.15
            assert len(connections) == 2 and all(c.closed for c in connections)
            assert all(c.deadline <= started + 2.02 for c in connections)
            assert abs(connections[0].deadline - connections[1].deadline) < 0.02
            assert ticks >= 10  # Native libpq waiting did not block the event loop.

            def consumer_read() -> float:
                with database.connect_task_io(timeout_seconds=0.5) as connection:
                    assert isinstance(connection, TaskIoConnection)
                    assert connection.execute("SELECT 1").fetchone() is not None
                    return connection.deadline - monotonic()

            # A consumer's later read inherits no expired scope from the failed worker job.
            assert await asyncio.to_thread(consumer_read) > 0.3
        finally:
            ticker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await ticker

    asyncio.run(check())
    assert pg_rows(replay.dsn) == before
