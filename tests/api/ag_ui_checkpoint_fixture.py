"""Explicit derived maintenance before observation; never invoked by GET."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.agent_tasks import AgentTaskPort, TaskEventPage
from agent_core.ports.task_projection_checkpoints import ProjectionScope
from agent_integrations.ag_ui import AgUiRunIdentity
from agent_integrations.ag_ui.checkpoint_binding import build_projection_page_plan
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
from agent_integrations.ag_ui.checkpoint_plan import AG_UI_CHECKPOINT_VERSION
from agent_storage import (
    ControlPlaneStores,
    SQLiteEventStore,
    sqlite_control_plane_stores,
)
from zebra_agent_api import ag_ui_stream
from zebra_agent_api.ag_ui_stream import _DisconnectableRequest

from tests.api.ag_ui_checkpoint_postgres_support import PgGetReplay, PgSqlObservation, pg_rows
from tests.api.ag_ui_checkpoint_postgres_support import pg_get_replay as _pg_get_replay
from tests.api.ag_ui_checkpoint_postgres_support import (
    test_cloud_pg_tail_read_shares_grant_deadline_and_cleans_native_query as _native_tail_deadline,
)
from tests.api.ag_ui_checkpoint_postgres_support import (
    test_native_tail_read_cumulative_budget_and_scope_restore as _native_read_scope,
)
from tests.api.ag_ui_checkpoint_postgres_support import (
    test_sql_observation_covers_real_native_task_io_connection as _native_sql_observation,
)

pg_get_replay = _pg_get_replay
test_sql_observation_covers_real_native_task_io_connection = _native_sql_observation
test_cloud_pg_tail_read_shares_grant_deadline_and_cleans_native_query = _native_tail_deadline
test_native_tail_read_cumulative_budget_and_scope_restore = _native_read_scope


def checkpoint_stores(
    path: Path,
    session_id: SessionId,
    run_id: str,
) -> ControlPlaneStores:
    stores = sqlite_control_plane_stores(path)
    prepare_checkpoint(stores, session_id, run_id)
    return stores


def prepare_checkpoint(
    stores: ControlPlaneStores,
    session_id: SessionId,
    run_id: str,
    *,
    namespace: str = "local",
    through_sequence: int | None = None,
) -> None:
    """Explicit bounded test preparation for either real adapter, always outside GET."""
    tasks = stores.tasks
    task = tasks.ensure_for_session(session_id)
    while not tasks.backfill_event_positions(task.task_id, limit=256):
        pass
    while not tasks.backfill_replay_headers(task.task_id, limit=256):
        pass
    while not tasks.backfill_projection_sources(task.task_id, limit=256):
        pass
    identity = AgUiRunIdentity(
        session_id=task.active_segment_id,
        thread_id=str(task.task_id),
        run_id=run_id,
    )
    run = tasks.read_run_header(task.task_id, run_id)
    if run.control_only or (not run.legacy and run.anchor is None):
        return
    scope = ProjectionScope(
        namespace,
        task.task_id,
        run.anchor.event_id if run.anchor else None,
        AG_UI_CHECKPOINT_VERSION,
    )
    materializer = AgUiCheckpointMaterializer(tasks)
    after = tasks.read_checkpoint_head(scope).through_sequence
    through = run.highwater if through_sequence is None else min(through_sequence, run.highwater)
    while after < through:
        page = tasks.read_event_page(
            task.task_id,
            after,
            limit=min(256, through - after),
            max_bytes=1_048_576,
            through_sequence=run.highwater,
        )
        assert page.events and len(page.events) <= 256 and page.byte_count <= 1_048_576
        plan = build_projection_page_plan(tasks, page, run, scope, identity)
        transition = materializer.prepare_page(page, plan, scope, identity)
        assert transition is not None
        tasks.commit_projection_page(transition)
        after = page.next_sequence
        assert tasks.read_checkpoint_head(scope).through_sequence == after


class ObservationTasks:
    """Reject writes/history; record only bounded Page hydration by the tail."""

    def __init__(self, delegate: AgentTaskPort) -> None:
        self.delegate = delegate
        self.pages: list[tuple[int, int, int]] = []
        self.page_sizes: list[tuple[int, int]] = []
        self.allow_bodies = False

    def __getattr__(self, name: str) -> Any:
        if name in {"read_events", "segments", "commit_projection_page", "ensure_for_session"} or (
            name.startswith("backfill") or name.startswith("rebuild")
        ):
            raise AssertionError(f"observer attempted {name}")
        return getattr(self.delegate, name)

    def read_event_page(
        self,
        task_id: TaskId,
        after_sequence: int,
        *,
        limit: int = 256,
        max_bytes: int = 1_048_576,
        through_sequence: int | None = None,
    ) -> TaskEventPage:
        assert self.allow_bodies, "preflight hydrated an Event body"
        assert 1 <= limit <= 256 and max_bytes <= 1_048_576
        self.pages.append((after_sequence, limit, max_bytes))
        page = self.delegate.read_event_page(
            task_id,
            after_sequence,
            limit=limit,
            max_bytes=max_bytes,
            through_sequence=through_sequence,
        )
        assert len(page.events) <= limit and page.byte_count <= max_bytes
        self.page_sizes.append((len(page.events), page.byte_count))
        return page


def table_rows(path: Path) -> dict[str, tuple[tuple[object, ...], ...]]:
    """Scratch fixture snapshots outside GET, never a production replay fallback."""
    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {
            name: tuple(sorted(connection.execute(f'SELECT * FROM "{name}"').fetchall(), key=repr))
            for (name,) in tables
        }


class SqlObservation:
    """Reject writes even if GET catches SQL errors; record executed body seeks."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, path: Path, *, bodies: bool) -> None:
        self.writes: list[tuple[int, str | None, str | None]] = []
        self.body_reads: list[str] = []
        self.statements: list[str] = []
        self.bodies = bodies
        connect = sqlite3.connect
        writes = {
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_CREATE_INDEX,
            sqlite3.SQLITE_CREATE_TRIGGER,
            sqlite3.SQLITE_DROP_TABLE,
            sqlite3.SQLITE_DROP_INDEX,
            sqlite3.SQLITE_DROP_TRIGGER,
            sqlite3.SQLITE_ALTER_TABLE,
        }

        def authorize(
            operation: int,
            table: str | None,
            column: str | None,
            _database: str | None,
            _trigger: str | None,
        ) -> int:
            if operation in writes:
                self.writes.append((operation, table, column))
                return sqlite3.SQLITE_DENY
            if (
                operation == sqlite3.SQLITE_READ
                and table == "session_events"
                and column == "payload"
            ):
                self.body_reads.append(column)
                if not self.bodies:
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        def observed_connect(
            database: str | Path,
            *args: Any,
            **kwargs: Any,
        ) -> sqlite3.Connection:
            connection: sqlite3.Connection = connect(database, *args, **kwargs)
            target = str(database)
            location = unquote(urlsplit(target).path) if target.startswith("file:") else target
            if Path(location).absolute() == path.absolute():
                connection.set_authorizer(authorize)
                connection.set_trace_callback(self.statements.append)
            return connection

        monkeypatch.setattr(sqlite3, "connect", observed_connect)

    def assert_bounded_body_seeks(self, *, pages: int) -> None:
        queries = [" ".join(statement.split()) for statement in self.statements]
        bodies = [
            query
            for query in queries
            if re.search(r"\bFROM session_events\b", query, re.IGNORECASE)
            and (re.search(r"\bpayload\b", query, re.IGNORECASE) or "SELECT *" in query)
        ]
        assert len(bodies) == pages, {"body_seeks": len(bodies), "expected_pages": pages}
        assert all(
            query.startswith("SELECT * FROM session_events WHERE task_id=")
            and "AND task_sequence>" in query
            and "AND task_sequence<=" in query
            and re.search(r"ORDER BY task_sequence LIMIT (\d+)$", query)
            and 1 <= int(query.rsplit(" ", 1)[1]) <= 256
            for query in bodies
        )


def checkpoint_backlog(
    tmp_path: Path,
    count: int = 100,
) -> tuple[Path, SessionId, int, ControlPlaneStores]:
    from agent_core.domain.events import EventType

    from tests.api.test_agui_stream_routes import _append, _seed_ready_session

    path, session, sequence = _seed_ready_session(tmp_path)
    event_store = SQLiteEventStore(path)
    _append(
        event_store,
        session,
        sequence,
        EventType.SESSION_COMMAND_ACCEPTED,
        {"payload": {"run_id": "run-1"}},
    )
    for offset in range(1, count):
        _append(
            event_store,
            session,
            sequence + offset,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": f"call-{offset}", "assistant_message": f"text-{offset}"},
        )
    stores = checkpoint_stores(path, session, "run-1")
    return path, session, sequence, stores


def queue_problem_context(
    tmp_path: Path,
    code: str,
    *,
    attempts: int = 1,
    retry_after: float | None = None,
    prefix: int = 0,
) -> ag_ui_stream.AgUiStreamContext:
    """Persist a real exact-scope problem with initial head -1, outside observation."""
    from agent_core.domain.events import EventType

    from tests.api.test_agui_stream_routes import _append, _seed_ready_session

    path, session, start = _seed_ready_session(tmp_path)
    _append(
        SQLiteEventStore(path),
        session,
        start,
        EventType.SESSION_COMMAND_ACCEPTED,
        {"payload": {"run_id": "problem-run"}},
    )
    for offset in range(1, prefix + 2) if prefix else ():
        _append(
            SQLiteEventStore(path),
            session,
            start + offset,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": f"prefix-{offset}", "assistant_message": f"answer-{offset}"},
        )
    stores = sqlite_control_plane_stores(path)
    task = stores.tasks.ensure_for_session(session)
    while not stores.tasks.backfill_event_positions(task.task_id, limit=256):
        pass
    while not stores.tasks.backfill_replay_headers(task.task_id, limit=256):
        pass
    while not stores.tasks.backfill_projection_sources(task.task_id, limit=256):
        pass
    if prefix:
        prepare_checkpoint(stores, session, "problem-run", through_sequence=start + prefix)
    work = stores.projection_work
    assert work is not None
    work.enable_projection_work()
    assert work.bootstrap_projection_work(limit=32)
    while work.repair_projection_work(task.task_id, limit=256).needs_repair:
        pass
    for attempt in range(1, attempts + 1):
        (pending,) = work.read_pending_projection_work(limit=32)
        assert pending.run_id == "problem-run"
        assert (
            pending.after_sequence
            == stores.tasks.read_checkpoint_head(pending.scope).through_sequence
        )
        assert work.defer_projection_work(
            pending, problem_code=code, retry_after_seconds=retry_after
        )
        if attempt < attempts:
            assert work.retry_projection_work(pending.scope, expected_attempt=attempt)
    assert stores.tasks.read_checkpoint_head(pending.scope).through_sequence == (
        start + prefix if prefix else -1
    )
    return ag_ui_stream.AgUiStreamContext(
        stores,
        task.task_id,
        AgUiRunIdentity(session_id=session, thread_id=str(task.task_id), run_id="problem-run"),
        None,
    )


def test_cloud_pg_legacy_missing_task_get_is_retryable_and_read_only(
    pg_get_replay: PgGetReplay,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.api.test_extension_reads import AUTH

    replay = pg_get_replay
    client = replay.client()
    before = pg_rows(replay.dsn)
    with monkeypatch.context() as patch:
        observed = PgSqlObservation(patch)
        response = client.get(f"/agui/threads/{replay.session}/runs/legacy/stream", headers=AUTH)
        assert observed.writes == [] and observed.body_reads == []
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "projection_not_ready"
        assert response.json()["retryable"] is True
    assert pg_rows(replay.dsn) == before


@pytest.mark.parametrize("stopped", [False, True])
def test_cloud_pg_get_frames_scope_and_deadline_are_read_only(
    pg_get_replay: PgGetReplay,
    monkeypatch: pytest.MonkeyPatch,
    stopped: bool,
) -> None:
    import asyncio
    from datetime import timedelta

    from agent_core.domain.host_authority import HostContextEnvelope
    from agent_integrations.ag_ui import AgUiCursor
    from zebra_agent_api import stream_v2_http

    from tests.api.test_agui_stream_routes import _FakeRequest
    from tests.api.test_extension_reads import AUTH

    replay = pg_get_replay
    replay.prepare_run(stopped=stopped)
    identity = AgUiRunIdentity(
        session_id=replay.session, thread_id=str(replay.session), run_id="run-1"
    )
    expected = [
        f
        for _, f in ag_ui_stream._project_new_task_events(
            replay.stores().tasks.read_events(TaskId(replay.session), -1),
            identity,
            None,
        )
    ]
    assert len(expected) >= 5
    path = f"/agui/threads/{replay.session}/runs/run-1/stream"
    client = replay.client()
    contexts: list[ag_ui_stream.AgUiStreamContext] = []
    before = pg_rows(replay.dsn)
    prepare, snapshot = ag_ui_stream.prepare_agui_stream, AgUiCheckpointObserver.snapshot
    expired = False
    completed_io: list[bool] = []
    with monkeypatch.context() as patch:
        observed = PgSqlObservation(patch)

        def preflight(*args: Any, **kwargs: Any) -> Any:
            observed.bodies = False
            body_reads = len(observed.body_reads)
            context = prepare(*args, **kwargs)
            assert len(observed.body_reads) == body_reads
            if isinstance(context, ag_ui_stream.AgUiStreamContext):
                if expired:
                    context = replace(
                        context,
                        authorization_expires_at=datetime.now(UTC) + timedelta(seconds=0.04),
                    )
                contexts.append(context)
                observed.bodies = True
            return context

        patch.setattr(stream_v2_http, "prepare_agui_stream", preflight)
        response = client.get(path, headers=AUTH)
        assert response.status_code == 200 and response.text == "".join(expected)
        assert not stopped or "RUN_FINISHED" not in response.text
        context = contexts[0]

        async def disconnect(cut: int) -> list[str]:
            request = _FakeRequest()
            stream = cast(
                AsyncGenerator[str, None], ag_ui_stream.tail_agui_events(context, request)
            )
            try:
                prefix = [await asyncio.wait_for(anext(stream), 1) for _ in range(cut)]
                request.disconnected = True
                with pytest.raises(StopAsyncIteration):
                    await asyncio.wait_for(anext(stream), 1)
                return prefix
            finally:
                await stream.aclose()

        for cut in range(1, len(expected) + 1):
            prefix = asyncio.run(disconnect(cut))
            assert prefix == expected[:cut]
            cursor = AgUiCursor.decode(prefix[-1].splitlines()[0].removeprefix("id: "))
            response = client.get(path, headers=AUTH, params={"cursor": cursor.encode()})
            assert response.status_code == 200 and response.text == "".join(expected[cut:])
        for changes in ({"run_id": "foreign-run"}, {"event_id": str(uuid4())}):
            response = client.get(
                path, headers=AUTH, params={"cursor": cursor.model_copy(update=changes).encode()}
            )
            assert response.status_code == 400 and response.json()["code"] == "invalid_cursor"
        foreign = replace(
            replay.verified,
            context=HostContextEnvelope.model_validate(
                {
                    **replay.verified.context.model_dump(),
                    "namespace_id": "tenant-b",
                }
            ),
        )
        assert foreign.context.namespace_id != replay.verified.context.namespace_id
        response = replay.client(foreign).get(path, headers=AUTH)
        assert response.status_code == 404 and "retryable" not in response.json()
        expired = True

        def slow_metadata(self: AgUiCheckpointObserver, *args: Any) -> Any:
            if observed.bodies:
                with psycopg.connect(replay.readonly_dsn) as connection:
                    connection.execute("SELECT pg_sleep(0.15)")
                completed_io.append(True)
            return snapshot(self, *args)

        patch.setattr(AgUiCheckpointObserver, "snapshot", slow_metadata)
        response = client.get(path, headers=AUTH)
        assert response.status_code == 200 and response.text == "" and completed_io == [True]
        assert observed.writes == [] and observed.body_reads
        assert observed.rejected_body_reads == []
        assert {"Connection", "TaskIoConnection"} <= observed.connections
        assert set(observed.body_connections) == {"TaskIoConnection"}
    assert pg_rows(replay.dsn) == before


@pytest.mark.parametrize(
    "code,attempts,scheduled,expected,retryable",
    [
        ("budget", 1, False, "projection_budget_exceeded", False),
        ("integrity", 1, False, "projection_conflict", False),
        ("projection_failed", 8, False, "observation_unavailable", False),
        ("projection_failed", 1, True, "projection_retry_scheduled", True),
        ("not_ready", 1, False, None, True),
    ],
)
def test_cloud_pg_complete_prefix_precedes_exact_scope_persisted_problem(
    pg_get_replay: PgGetReplay,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    attempts: int,
    scheduled: bool,
    expected: str | None,
    retryable: bool,
) -> None:
    import json

    from agent_core.ports.task_projection_work import ProjectionWorkProblem
    from agent_storage.postgres.command_wakeup_outcome import PostgresCommandOutcomeReader
    from zebra_agent_api import stream_v2_http

    from tests.api.test_extension_reads import AUTH

    replay = pg_get_replay
    scope = replay.prepare_problem(code, attempts=attempts, retry_after=60 if scheduled else None)
    stores = replay.stores()
    head = stores.tasks.read_checkpoint_head(scope)
    anchor = stores.tasks.read_run_header(scope.task_id, "run-1").anchor
    assert anchor is not None
    reader = PostgresCommandOutcomeReader(replay.readonly_dsn, deployment_namespace=scope.namespace)
    with monkeypatch.context() as patch:
        admission = PgSqlObservation(patch)
        assert reader(scope.task_id, "run-1", anchor.event_id, replay.verified.context) is None
        assert admission.writes == [] and admission.body_reads == []
        assert len(admission.command_points) == 1
    identity = AgUiRunIdentity(
        session_id=replay.session, thread_id=str(scope.task_id), run_id="run-1"
    )
    entries = tuple(
        e
        for e in stores.tasks.read_events(scope.task_id, -1)
        if e.task_sequence <= head.through_sequence
    )
    prefix = [frame for _, frame in ag_ui_stream._project_new_task_events(entries, identity, None)]
    # Bootstrap warmed this Segment before the bound Run; it must not restart here.
    assert len(prefix) == 780  # All three frames of 260 canonical model Events.
    assert not any('"type":"RUN_STARTED"' in frame for frame in prefix)
    work = stores.projection_work
    assert work is not None
    read, prepare, tail = (
        type(work).read_projection_work_problem,
        ag_ui_stream.prepare_agui_stream,
        ag_ui_stream.tail_agui_events,
    )
    seen: list[ProjectionScope] = []
    pages: list[ObservationTasks] = []
    before = pg_rows(replay.dsn)
    client = replay.client()
    with monkeypatch.context() as patch:
        observed = PgSqlObservation(patch)

        def scoped(self: Any, requested: ProjectionScope) -> ProjectionWorkProblem | None:
            seen.append(requested)
            return read(self, requested)

        def preflight(*args: Any, **kwargs: Any) -> Any:
            observed.bodies = False
            context = prepare(*args, **kwargs)
            assert observed.body_reads == []
            assert isinstance(context, ag_ui_stream.AgUiStreamContext)
            tasks = ObservationTasks(context.stores.tasks)
            tasks.allow_bodies = observed.bodies = True
            pages.append(tasks)
            return replace(
                context, stores=replace(context.stores, tasks=cast(AgentTaskPort, tasks))
            )

        async def connection(
            context: ag_ui_stream.AgUiStreamContext,
            request: _DisconnectableRequest,
        ) -> AsyncGenerator[str, None]:
            async with aclosing(cast(AsyncGenerator[str, None], tail(context, request))) as source:
                async for frame in source:
                    yield frame
                    if not frame.startswith("id: "):
                        return  # Client disconnect only after the real problem/wait frame.

        patch.setattr(type(work), "read_projection_work_problem", scoped)
        patch.setattr(stream_v2_http, "prepare_agui_stream", preflight)
        patch.setattr(stream_v2_http, "tail_agui_events", connection)
        response = client.get(f"/agui/threads/{replay.session}/runs/run-1/stream", headers=AUTH)
        assert response.status_code == 200 and response.text.startswith("".join(prefix))
        suffix = response.text[len("".join(prefix)) :]
        if expected is None:
            assert suffix == ": keepalive\n\n"  # Dependency wait; never fabricated Task failure.
        else:
            notice = json.loads(suffix.removeprefix("data: "))
            assert notice["type"] == "CUSTOM" and notice["name"] == "zebra.observation.problem"
            assert notice["value"] == {"code": expected, "retryable": retryable}
            assert "id: " not in suffix
        assert "RUN_ERROR" not in response.text and "RUN_FINISHED" not in response.text
        assert seen and all(requested == scope for requested in seen)
        assert observed.writes == [] and observed.body_limits == [256, 5]
        assert observed.rejected_body_reads == [], observed.rejected_body_reads
        assert "TaskIoConnection" in observed.connections
        assert set(observed.body_connections) == {"TaskIoConnection"}
        point = (
            scope.namespace,
            scope.task_id,
            anchor.task_sequence,
            anchor.event_id,
            anchor.segment_id,
            anchor.segment_sequence,
        )
        assert observed.command_points and all(p == point for p in observed.command_points)
        assert set(observed.command_connections) == {"TaskIoConnection"}
        assert len(pages) == 1 and [size for size, _ in pages[0].page_sizes] == [256, 5]
        assert all(
            limit == 256 and byte_limit == 1_048_576 for _, limit, byte_limit in pages[0].pages
        )
    assert pg_rows(replay.dsn) == before


def test_scheduled_problem_recovers_after_external_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import json
    from time import monotonic

    from agent_core.domain.events import EventType
    from zebra_agent_api.ag_ui_checkpoint_tail import tail_checkpoint_frames

    from tests.api.test_agui_stream_routes import _append, _FakeRequest

    context = queue_problem_context(tmp_path, "projection_failed", retry_after=60)
    work = context.stores.projection_work
    assert work is not None
    snapshot = AgUiCheckpointObserver(context.stores.tasks, namespace="local").snapshot(
        context.task_id, context.identity
    )
    path = tmp_path / "sessions.sqlite"

    async def check() -> None:
        stream = tail_checkpoint_frames(
            context,
            _FakeRequest(),
            monotonic() + 2,
            poll_seconds=0.005,
            keepalive_seconds=1,
        )
        try:
            before = table_rows(path)
            with monkeypatch.context() as patch:
                sql_guard = SqlObservation(patch, path, bodies=False)
                first = await asyncio.wait_for(anext(stream), 0.3)
                assert json.loads(first.removeprefix("data: "))["value"] == {
                    "code": "projection_retry_scheduled",
                    "retryable": True,
                }
                assert sql_guard.writes == [] and sql_guard.body_reads == []
            assert table_rows(path) == before
            # Only an external producer/repair changes state, never the suspended SSE observer.
            assert work.retry_projection_work(snapshot.head.scope, expected_attempt=1)
            source = SQLiteEventStore(path)
            _append(
                source,
                context.identity.session_id,
                snapshot.run.highwater + 1,
                EventType.MODEL_RESPONSE_RECEIVED,
                {"model_call_id": "recovered", "assistant_message": "recovered answer"},
            )
            _append(
                source,
                context.identity.session_id,
                snapshot.run.highwater + 2,
                EventType.SESSION_COMPLETED,
                {},
            )
            prepare_checkpoint(context.stores, context.identity.session_id, "problem-run")
            before = table_rows(path)
            with monkeypatch.context() as patch:
                sql_guard = SqlObservation(patch, path, bodies=True)
                async with asyncio.timeout(0.5):
                    frames = [frame async for frame in stream]
                assert "recovered answer" in "".join(frames)
                assert "RUN_FINISHED" in "".join(frames)
                assert not any("zebra.observation.problem" in frame for frame in frames)
                assert sql_guard.writes == []
            assert table_rows(path) == before
        finally:
            await stream.aclose()

    asyncio.run(check())
