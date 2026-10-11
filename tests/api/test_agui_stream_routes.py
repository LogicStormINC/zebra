from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from ag_ui.core import Event
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_tasks import AgentTask
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId, new_event_id
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.agent_tasks import AgentTaskPort, TaskEvent, TaskEventPage
from agent_core.ports.task_projection_checkpoints import CheckpointStale
from agent_integrations.ag_ui import AgUiCursor, AgUiRunIdentity
from agent_integrations.ag_ui.checkpoint_observer import (
    AgUiCheckpointObserver,
    AgUiObservationSnapshot,
)
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
    sqlite_control_plane_stores,
)
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from zebra_agent_api.ag_ui_stream import (
    AgUiStreamContext,
    _cursor_before_run,
    _run_command_is_not_indexed,
    prepare_agui_stream,
    tail_agui_events,
)
from zebra_agent_api.http import _stream_resource_id, create_http_app
from zebra_agent_api.responses import ApiResponse

from tests.api.ag_ui_checkpoint_fixture import SqlObservation, checkpoint_stores, table_rows

NOW = datetime(2026, 8, 11, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize("frame", ["projection", "ambiguous-error", ": keepalive\n\n"])
def test_shared_frame_gate_checks_after_await_and_before_next_source_read(monkeypatch, frame):
    from zebra_agent_api import ag_ui_task_view

    clock, reads = [0.0], []
    monkeypatch.setattr(ag_ui_task_view, "monotonic", lambda: clock[0])

    async def source():
        reads.append(True)
        clock[0] = 2.0
        yield frame
        reads.append(True)

    async def consume():
        return [item async for item in ag_ui_task_view.deadline_frames(source(), 1.0)]

    assert asyncio.run(consume()) == []
    assert reads == [True]


@pytest.mark.parametrize("native_task", [False, True])
def test_actual_segments_get_never_adopts_a_legacy_session(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    native_task: bool,
) -> None:
    path, session, _ = _seed_ready_session(tmp_path)
    stores = sqlite_control_plane_stores(path)
    if native_task:
        stores.tasks.ensure_for_session(session)
    client = TestClient(create_http_app(path, stores=stores))
    before = table_rows(path)
    with monkeypatch.context() as patch:
        sql = SqlObservation(patch, path, bodies=False)
        response = client.get(f"/internal/tasks/{session}/segments")
        assert sql.writes == [] and sql.body_reads == []
        assert response.status_code == (200 if native_task else 404), response.text
        segments = stores.tasks.segments(TaskId(session))
        assert len(segments) == (1 if native_task else 0)
        assert sql.writes == [] and sql.body_reads == []
    assert table_rows(path) == before


def test_foreign_legacy_session_get_is_hidden_before_checkpoint_preflight(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

    from tests.api.test_tenant_isolation import TENANT_B

    path, session, _ = _seed_ready_session(tmp_path)
    stores = sqlite_control_plane_stores(path)
    projection = stores.sessions.get_session(session)
    assert projection is not None and stores.tasks.get_task(TaskId(session)) is None
    stores.sessions.save_session(projection.model_copy(update={"namespace_id": "tenant-a"}))
    app = create_http_app(path, stores=stores)

    @app.middleware("http")
    async def authenticated_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.host_context = TENANT_B  # Grant verification is outside this tenant probe.
        return await call_next(request)

    def forbidden_preflight(*args: object, **kwargs: object) -> None:
        raise AssertionError("foreign Session reached checkpoint preflight")

    client = TestClient(app)
    before = table_rows(path)
    with monkeypatch.context() as patch:
        patch.setattr("zebra_agent_api.http.prepare_agui_stream", forbidden_preflight)
        sql = SqlObservation(patch, path, bodies=False)
        response = client.get(_stream_path(session, "legacy"))
        assert response.status_code == 404 and response.json()["status"] == "not_found"
        assert "projection_not_ready" not in response.text and "retryable" not in response.text
        assert sql.writes == [] and sql.body_reads == []
    assert table_rows(path) == before


def test_production_runner_discovers_closed_task_without_new_source_appends(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    import sqlite3
    from time import monotonic, sleep

    from agent_core.ports.task_projection_checkpoints import CheckpointNotReady, ProjectionScope
    from agent_integrations.ag_ui.checkpoint_plan import AG_UI_CHECKPOINT_VERSION
    from zebra_agent_worker import build_worker_loop_service

    from tests.worker.execution.worker_execution_support import _settings

    path, session, start = _seed_ready_session(tmp_path)
    source = SQLiteEventStore(path)
    _append(
        source, session, start, EventType.SESSION_COMMAND_ACCEPTED, {"payload": {"run_id": "old"}}
    )
    _append(
        source,
        session,
        start + 1,
        EventType.MODEL_RESPONSE_RECEIVED,
        {"model_call_id": "old-model", "assistant_message": "already completed"},
    )
    _append(source, session, start + 2, EventType.SESSION_COMPLETED, {})
    stores = sqlite_control_plane_stores(path)
    stores.tasks.ensure_for_session(session)  # Admission only; no derived preparation fixture.
    canonical = tuple(source.list_for_session(session))
    client = TestClient(create_http_app(path, stores=stores))
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM task_projection_work").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM task_projection_work_projectors WHERE enabled=1"
            ).fetchone()[0]
            == 0
        )
    with monkeypatch.context() as patch:
        sql = SqlObservation(patch, path, bodies=False)
        unready = client.get(_stream_path(session, "old"))
        assert unready.status_code == 409 and unready.json()["code"] == "projection_not_ready"
        assert sql.writes == [] and sql.body_reads == []
    loop = build_worker_loop_service(database_path=path, settings=_settings(path), stores=stores)
    try:
        assert loop._projection_work is not None
        loop.maintenance_once(worker_id="old-task-discovery", batch_size=1, lease_ttl_seconds=30)
        deadline = monotonic() + 3
        while True:
            try:
                run = stores.tasks.read_run_header(TaskId(session), "old")
                assert run.anchor is not None
                scope = ProjectionScope(
                    "local", TaskId(session), run.anchor.event_id, AG_UI_CHECKPOINT_VERSION
                )
                if stores.tasks.read_checkpoint_head(scope).through_sequence == run.highwater:
                    break
            except CheckpointNotReady:
                pass
            assert monotonic() < deadline, "runner did not discover the already closed Task"
            sleep(0.01)
    finally:
        loop.drain()
    assert tuple(source.list_for_session(session)) == canonical
    before = table_rows(path)
    with monkeypatch.context() as patch:
        sql = SqlObservation(patch, path, bodies=True)
        response = client.get(_stream_path(session, "old"))
        assert response.status_code == 200, response.text
        assert "already completed" in response.text and "RUN_FINISHED" in response.text
        assert sql.writes == []
        sql.assert_bounded_body_seeks(pages=1)
    assert table_rows(path) == before


def test_checkpoint_stale_is_read_only_observation_problem_not_task_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    path, session, next_sequence = _seed_ready_session(tmp_path)
    _append(SQLiteEventStore(path), session, next_sequence, EventType.SESSION_COMPLETED, {})
    stores = checkpoint_stores(path, session, "legacy")
    client = TestClient(create_http_app(path, stores=stores))
    context = prepare_agui_stream(stores, _stream_path(session, "legacy"), {})
    assert isinstance(context, AgUiStreamContext)
    before = table_rows(path)

    def stale_head(
        self: AgUiCheckpointObserver,
        task_id: TaskId,
        identity: AgUiRunIdentity,
    ) -> AgUiObservationSnapshot:
        raise CheckpointStale("another builder advanced this frontier")

    async def consume() -> str:
        async with asyncio.timeout(1):
            return "".join([frame async for frame in tail_agui_events(context, _FakeRequest())])

    with monkeypatch.context() as patch:
        patch.setattr(AgUiCheckpointObserver, "snapshot", stale_head)
        sql = SqlObservation(patch, path, bodies=False)
        rejected = client.get(_stream_path(session, "legacy"))
        assert rejected.status_code == 409 and rejected.json()["code"] == "projection_conflict"
        output = asyncio.run(consume())
        assert "zebra.observation.problem" in output and "projection_conflict" in output
        assert '"type":"CUSTOM"' in output
        assert "id: " not in output and "RUN_ERROR" not in output and "RUN_FINISHED" not in output
        assert sql.writes == [] and sql.body_reads == []
    assert table_rows(path) == before


def test_checkpoint_tail_disconnect_during_frame_read_emits_nothing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    path, session, next_sequence = _seed_ready_session(tmp_path)
    _append(SQLiteEventStore(path), session, next_sequence, EventType.SESSION_COMPLETED, {})
    context = prepare_agui_stream(
        checkpoint_stores(path, session, "legacy"),
        _stream_path(session, "legacy"),
        {},
    )
    assert isinstance(context, AgUiStreamContext)
    request = _FakeRequest()
    original = AgUiCheckpointObserver.iter_page_frames
    read: list[AgUiCursor] = []

    def disconnect_during_read(
        self: AgUiCheckpointObserver,
        snapshot: AgUiObservationSnapshot,
        page: TaskEventPage,
        identity: AgUiRunIdentity,
        *,
        after: AgUiCursor | None = None,
    ) -> Iterator[tuple[AgUiCursor, Event]]:
        for frame in original(self, snapshot, page, identity, after=after):
            read.append(frame[0])
            request.disconnected = True
            yield frame

    monkeypatch.setattr(AgUiCheckpointObserver, "iter_page_frames", disconnect_during_read)

    async def consume() -> list[str]:
        async with asyncio.timeout(1):
            return [frame async for frame in tail_agui_events(context, request)]

    assert asyncio.run(consume()) == []
    assert len(read) == 1  # Real frame was available; it was not encoded/emitted after disconnect.


def test_agui_stream_tenant_guard_uses_thread_id_not_run_id() -> None:
    assert (
        _stream_resource_id(
            "/agui/threads/283f65ec-a279-453d-ac4a-59f2e5da6ccd/"
            "runs/bd617b73-2e21-4dbc-b3f9-ceb786fdce51/stream"
        )
        == "283f65ec-a279-453d-ac4a-59f2e5da6ccd"
    )


def test_agui_stream_never_renews_execution_binding(monkeypatch, tmp_path: Path) -> None:
    database_path, session_id, _ = _seed_ready_session(tmp_path)
    calls: list[str] = []

    def reject_renewal(app, task_id, verified_host_grant):
        del app, verified_host_grant
        calls.append(task_id)
        return ApiResponse(403, {"status": "host_binding_renewal_rejected"})

    monkeypatch.setattr(
        "zebra_agent_api.session_binding.renew_host_binding_for_command",
        reject_renewal,
    )
    client = TestClient(
        create_http_app(database_path, stores=sqlite_control_plane_stores(database_path))
    )
    response = client.get(_stream_path(session_id, "run-renewal"))

    assert calls == []
    assert response.status_code == 409  # Legacy projection is not ready, not a renewal failure.
    assert response.json()["code"] == "projection_not_ready"


def test_agui_stream_replays_official_events_with_exact_cursor_ids(tmp_path: Path) -> None:
    database_path, session_id, next_sequence = _seed_ready_session(tmp_path)
    event_store = SQLiteEventStore(database_path)
    _append(event_store, session_id, next_sequence, EventType.TASK_PREPARED, {"title": "Task"})
    _append(
        event_store,
        session_id,
        next_sequence + 1,
        EventType.RUNTIME_PROVISIONED,
        {"runtime_id": "ignored"},
    )
    delta = _append(
        event_store,
        session_id,
        next_sequence + 2,
        EventType.MODEL_RESPONSE_DELTA,
        {"model_call_id": "model-1", "content_delta": "hello"},
    )
    _append(
        event_store,
        session_id,
        next_sequence + 3,
        EventType.MODEL_RESPONSE_RECEIVED,
        {"model_call_id": "model-1", "assistant_message": "hello"},
    )
    _append(event_store, session_id, next_sequence + 4, EventType.SESSION_COMPLETED, {})

    client = TestClient(
        create_http_app(database_path, stores=checkpoint_stores(database_path, session_id, "run-1"))
    )
    response = client.get(_stream_path(session_id, "run-1"))

    assert response.status_code == 200
    assert "RUN_STARTED" in response.text
    assert "TEXT_MESSAGE_CONTENT" in response.text
    assert "RUN_FINISHED" in response.text
    cursor = _cursor_for_sequence(response.text, delta.sequence)
    assert cursor is not None

    tail = client.get(f"{_stream_path(session_id, 'run-1')}?cursor={cursor}")

    assert tail.status_code == 200
    assert "RUN_STARTED" not in tail.text
    assert "TEXT_MESSAGE_END" in tail.text
    assert "RUN_FINISHED" in tail.text

    header_tail = client.get(
        _stream_path(session_id, "run-1"),
        headers={"Last-Event-ID": cursor},
    )
    assert header_tail.status_code == 200
    assert "RUN_STARTED" not in header_tail.text
    assert "RUN_FINISHED" in header_tail.text


def test_agui_stream_rejects_malformed_or_cross_run_cursor(tmp_path: Path) -> None:
    database_path, session_id, next_sequence = _seed_ready_session(tmp_path)
    event_store = SQLiteEventStore(database_path)
    event = _append(
        event_store,
        session_id,
        next_sequence,
        EventType.TASK_PREPARED,
        {"title": "Task"},
    )
    stores = checkpoint_stores(database_path, session_id, "run-1")
    cursor = AgUiCursor(
        thread_id=str(session_id),
        run_id="other-run",
        sequence=event.sequence,
        event_id=str(event.event_id),
    ).encode()
    client = TestClient(create_http_app(database_path, stores=stores))

    malformed = client.get(f"{_stream_path(session_id, 'run-1')}?cursor=bad")
    cross_run = client.get(f"{_stream_path(session_id, 'run-1')}?cursor={cursor}")

    assert malformed.status_code == 400
    assert malformed.json()["code"] == "invalid_cursor"
    assert cross_run.status_code == 400
    assert cross_run.json()["code"] == "invalid_cursor"
    assert "recovery_cursor" not in malformed.json()
    assert AgUiCursor.decode(cross_run.json()["recovery_cursor"]).event_id == str(event.event_id)


def test_agui_stream_closes_conversation_run_after_turn_completion(tmp_path: Path) -> None:
    database_path, session_id, next_sequence = _seed_ready_session(tmp_path)
    event_store = SQLiteEventStore(database_path)
    _append(
        event_store,
        session_id,
        next_sequence,
        EventType.TURN_COMPLETED,
        {
            "turn_id": "turn-1",
            "turn_index": 0,
            "closes_segment": False,
            "attempt_number": 1,
        },
    )
    _append(
        event_store,
        session_id,
        next_sequence + 1,
        EventType.SESSION_TITLE_UPDATED,
        {"title": "Generated title"},
    )
    client = TestClient(
        create_http_app(
            database_path, stores=checkpoint_stores(database_path, session_id, "run-conversation")
        )
    )

    response = client.get(_stream_path(session_id, "run-conversation"))

    assert response.status_code == 200
    assert "RUN_FINISHED" in response.text


def test_agui_stream_starts_at_the_current_run_command(tmp_path: Path) -> None:
    database_path, session_id, next_sequence = _seed_ready_session(tmp_path)
    event_store = SQLiteEventStore(database_path)
    _append(
        event_store,
        session_id,
        next_sequence,
        EventType.SESSION_COMMAND_ACCEPTED,
        {"payload": {"run_id": "old-run"}},
    )
    previous = _append(
        event_store,
        session_id,
        next_sequence + 1,
        EventType.USER_MESSAGE_RECEIVED,
        {"content": "next"},
    )
    _append(
        event_store,
        session_id,
        next_sequence + 2,
        EventType.SESSION_COMMAND_ACCEPTED,
        {"payload": {"run_id": "new-run"}},
    )
    stores = sqlite_control_plane_stores(database_path)
    stores.tasks.ensure_for_session(session_id)  # Explicit fixture admission before the oracle.
    events = stores.tasks.read_events(TaskId(session_id), -1)
    assert _run_command_is_not_indexed(events[:-1], "new-run")

    cursor = _cursor_before_run(
        events,
        AgUiRunIdentity(
            session_id=session_id,
            thread_id=str(session_id),
            run_id="new-run",
        ),
    )

    assert cursor is not None
    assert cursor.sequence == next_sequence + 1
    assert cursor.event_id == str(previous.event_id)


def test_agui_stream_does_not_replay_a_previous_run_in_the_same_segment(
    tmp_path: Path,
) -> None:
    database_path, session_id, next_sequence = _seed_ready_session(tmp_path)
    event_store = SQLiteEventStore(database_path)
    sequence = next_sequence
    cases: tuple[tuple[EventType, dict[str, object]], ...] = (
        (EventType.SESSION_COMMAND_ACCEPTED, {"payload": {"run_id": "old-run"}}),
        (
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "old-model", "assistant_message": "old-answer"},
        ),
        (
            EventType.TURN_COMPLETED,
            {"turn_id": "turn-1", "turn_index": 0, "closes_segment": False},
        ),
        (EventType.USER_MESSAGE_RECEIVED, {"content": "next"}),
        (EventType.SESSION_COMMAND_ACCEPTED, {"payload": {"run_id": "new-run"}}),
        (
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "new-model", "assistant_message": "new-answer"},
        ),
        (
            EventType.TURN_COMPLETED,
            {"turn_id": "turn-2", "turn_index": 1, "closes_segment": False},
        ),
    )
    for event_type, payload in cases:
        _append(event_store, session_id, sequence, event_type, payload)
        sequence += 1
    client = TestClient(
        create_http_app(
            database_path, stores=checkpoint_stores(database_path, session_id, "new-run")
        )
    )

    response = client.get(_stream_path(session_id, "new-run"))

    assert response.status_code == 200
    assert "new-answer" in response.text
    assert "old-answer" not in response.text


def test_agui_stream_live_tail_reads_event_store_when_task_index_is_stale(
    tmp_path: Path,
) -> None:
    database_path, session_id, next_sequence = _seed_ready_session(tmp_path)
    stores = checkpoint_stores(database_path, session_id, "run-live")
    frozen_tasks = _FrozenTaskStore(stores.tasks, TaskId(session_id))
    stores = replace(stores, tasks=cast(AgentTaskPort, frozen_tasks))
    context = prepare_agui_stream(
        stores,
        _stream_path(session_id, "run-live"),
        {},
    )
    assert isinstance(context, AgUiStreamContext)
    request = _FakeRequest()
    stream = tail_agui_events(context, request)

    from agent_storage.database import SQLiteDatabase
    from zebra_agent_api.ag_ui_stream import _project_new_task_events

    initial_count = len(list(_project_new_task_events(frozen_tasks.events, context.identity, None)))

    async def consume() -> tuple[str, str, str, str, str]:
        initial = [await anext(stream) for _ in range(initial_count)]
        late = _append(
            SQLiteEventStore(database_path),
            session_id,
            next_sequence,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "live-model", "assistant_message": "live"},
        )
        checkpoint_stores(database_path, session_id, "run-live")  # Simulated worker maintenance.
        with SQLiteDatabase(database_path).connect() as connection:
            connection.execute(
                "DELETE FROM task_event_index WHERE event_id=?", (str(late.event_id),)
            )
        live_start = await asyncio.wait_for(anext(stream), timeout=1)
        live_content = await asyncio.wait_for(anext(stream), timeout=1)
        live_end = await asyncio.wait_for(anext(stream), timeout=1)
        request.disconnected = True
        return initial[0], initial[1], live_start, live_content, live_end

    first, initial_state, live_start, live_content, live_end = asyncio.run(consume())

    assert "RUN_STARTED" in first or "STATE_SNAPSHOT" in first
    assert "STATE_SNAPSHOT" in initial_state
    assert "TEXT_MESSAGE_START" in live_start
    assert "TEXT_MESSAGE_CONTENT" in live_content
    assert "TEXT_MESSAGE_END" in live_end
    assert all(entry.event.sequence < next_sequence for entry in frozen_tasks.events)


def test_agui_stream_flushes_terminal_event_after_projection_status_race(
    tmp_path: Path,
) -> None:
    database_path, session_id, next_sequence = _seed_ready_session(tmp_path)
    stores = checkpoint_stores(database_path, session_id, "run-race")
    session = stores.sessions.get_session(session_id)
    assert session is not None
    stores.sessions.save_session(session.model_copy(update={"status": SessionStatus.COMPLETED}))
    context = prepare_agui_stream(stores, _stream_path(session_id, "run-race"), {})
    assert isinstance(context, AgUiStreamContext)
    stream = tail_agui_events(context, _FakeRequest())

    async def consume() -> str:
        async def append_terminal() -> None:
            await asyncio.sleep(0.75)
            _append(
                SQLiteEventStore(database_path),
                session_id,
                next_sequence,
                EventType.SESSION_COMPLETED,
                {},
            )
            checkpoint_stores(database_path, session_id, "run-race")

        delayed = asyncio.create_task(append_terminal())
        chunks = [chunk async for chunk in stream]
        await delayed
        return "".join(chunks)

    output = asyncio.run(consume())

    assert "RUN_FINISHED" in output


class _FakeRequest:
    disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


class _FrozenTaskStore:
    """Model PostgreSQL's explicitly rebuilt Task index during an active Turn."""

    def __init__(self, delegate: AgentTaskPort, task_id: TaskId) -> None:
        self._delegate = delegate
        self.events = delegate.read_events(task_id, -1)

    def __getattr__(self, name: str):
        # Only the old derived read_events view is frozen. New canonical Page,
        # scalar header and checkpoint interfaces delegate to the real adapter.
        return getattr(self._delegate, name)

    def get_task(self, task_id: TaskId) -> AgentTask | None:
        return self._delegate.get_task(task_id)

    def segments(self, task_id: TaskId):
        return self._delegate.segments(task_id)

    def read_events(self, task_id: TaskId, after_sequence: int) -> tuple[TaskEvent, ...]:
        return tuple(
            entry
            for entry in self.events
            if entry.task_id == task_id and entry.task_sequence > after_sequence
        )


def _stream_path(session_id: SessionId, run_id: str) -> str:
    return f"/agui/threads/{session_id}/runs/{run_id}/stream"


def _cursor_for_sequence(text: str, sequence: int) -> str | None:
    blocks = text.split("\n\n")
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 2 or not lines[0].startswith("id: "):
            continue
        try:
            cursor = AgUiCursor.decode(lines[0].removeprefix("id: "))
        except ValueError:
            continue
        if cursor.sequence == sequence:
            return lines[0].removeprefix("id: ")
    return None


def _append(
    store: SQLiteEventStore,
    session_id: SessionId,
    sequence: int,
    event_type: EventType,
    payload: dict[str, object],
) -> SessionEvent:
    if event_type is EventType.SESSION_COMMAND_ACCEPTED:
        payload = {"kind": "run", **payload}
    event = SessionEvent(
        event_id=new_event_id(),
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        payload=payload,
        actor=EventActor.HARNESS,
        created_at=NOW,
    )
    store.append(event)
    return event


def _seed_ready_session(tmp_path: Path) -> tuple[Path, SessionId, int]:
    database_path = tmp_path / "sessions.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="AG-UI stream",
            user_input="Replay the durable stream.",
            workspace_root=tmp_path.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        rebuild_workspace(list(bootstrap.events))
    )
    return database_path, bootstrap.session.session_id, bootstrap.session.current_sequence + 1
