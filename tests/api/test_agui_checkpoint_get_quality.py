"""Real GET/observer evidence; derived maintenance is never hidden inside GET."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from typing import Any, cast
from uuid import uuid4
from weakref import ReferenceType, ref

import pytest
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.agent_tasks import AgentTaskPort, TaskEvent, TaskEventPage
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady, ProjectionScope
from agent_integrations.ag_ui import AgUiCursor, AgUiRunIdentity
from agent_integrations.ag_ui.checkpoint_observer import (
    AgUiCheckpointObserver,
    AgUiObservationSnapshot,
)
from agent_integrations.ag_ui.checkpoint_plan import AG_UI_CHECKPOINT_VERSION
from agent_storage import ControlPlaneStores, SQLiteEventStore, sqlite_control_plane_stores
from fastapi.testclient import TestClient
from zebra_agent_api import ag_ui_stream, stream_v2_http
from zebra_agent_api.ag_ui_task_view import deadline_frames
from zebra_agent_api.http import create_http_app
from zebra_agent_api.responses import ApiResponse

from tests.api.ag_ui_checkpoint_fixture import ObservationTasks, checkpoint_stores
from tests.api.ag_ui_checkpoint_fixture import SqlObservation as _SqlObservation
from tests.api.ag_ui_checkpoint_fixture import table_rows as _rows
from tests.api.test_agui_stream_routes import (
    _append,
    _FakeRequest,
    _seed_ready_session,
    _stream_path,
)


@pytest.fixture(autouse=True)
def _bounded_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    # RED HTTP probes must finish too; never hide an absent production frontier.
    monkeypatch.setattr(ag_ui_stream, "_MAX_STREAM_SECONDS", 30.0)


@dataclass(frozen=True)
class _Replay:
    path: Path
    session: SessionId
    stores: ControlPlaneStores
    command: SessionEvent
    message: SessionEvent
    terminal: SessionEvent
    events: tuple[TaskEvent, ...]


def _closed_run(tmp_path: Path, *, messages: int = 2) -> _Replay:
    path, session, start = _seed_ready_session(tmp_path)
    source = SQLiteEventStore(path)
    command = _append(
        source,
        session,
        start,
        EventType.SESSION_COMMAND_ACCEPTED,
        {"payload": {"run_id": "run-1"}},
    )
    message = command
    for offset in range(messages):
        message = _append(
            source,
            session,
            start + offset + 1,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": f"model-{offset}", "assistant_message": f"answer-{offset}"},
        )
    terminal = _append(source, session, start + messages + 1, EventType.SESSION_COMPLETED, {})
    stores = checkpoint_stores(path, session, "run-1")
    events = stores.tasks.read_events(TaskId(session), -1)  # Oracle before observation.
    return _Replay(path, session, stores, command, message, terminal, events)


def _context(replay: _Replay, cursor: str | None = None) -> ag_ui_stream.AgUiStreamContext:
    result = ag_ui_stream.prepare_agui_stream(
        replay.stores,
        _stream_path(replay.session, "run-1"),
        {} if cursor is None else {"cursor": cursor},
    )
    assert isinstance(result, ag_ui_stream.AgUiStreamContext), result
    return result


async def _collect(context: ag_ui_stream.AgUiStreamContext) -> list[str]:
    async with asyncio.timeout(2):
        return [frame async for frame in ag_ui_stream.tail_agui_events(context, _FakeRequest())]


def _stream(
    context: ag_ui_stream.AgUiStreamContext,
    request: _FakeRequest,
) -> AsyncGenerator[str, None]:
    return cast(AsyncGenerator[str, None], ag_ui_stream.tail_agui_events(context, request))


def _cursor(frame: str) -> AgUiCursor:
    assert frame.startswith("id: "), frame
    return AgUiCursor.decode(frame.splitlines()[0].removeprefix("id: "))


def test_actual_get_eof_and_invalid_cursors_are_body_free_and_sql_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = _closed_run(tmp_path)
    tasks = ObservationTasks(replay.stores.tasks)
    stores = replace(replay.stores, tasks=cast(AgentTaskPort, tasks))
    client = TestClient(create_http_app(replay.path, stores=stores))
    before = _rows(replay.path)
    end = AgUiCursor(
        thread_id=str(replay.session),
        run_id="run-1",
        sequence=replay.terminal.sequence,
        event_id=str(replay.terminal.event_id),
    )
    forged = end.model_copy(update={"event_id": str(uuid4())})
    cross_run = end.model_copy(update={"run_id": "other-run"})
    with monkeypatch.context() as patch:
        sql = _SqlObservation(patch, replay.path, bodies=False)
        eof = client.get(_stream_path(replay.session, "run-1"), params={"cursor": end.encode()})
        invalid = [
            client.get(_stream_path(replay.session, "run-1"), params={"cursor": cursor})
            for cursor in ("bad", forged.encode(), cross_run.encode())
        ]
        assert eof.status_code == 200 and eof.text == ""
        assert [response.status_code for response in invalid] == [400, 400, 400]
        assert all(response.json()["code"] == "invalid_cursor" for response in invalid)
        assert sql.writes == [] and sql.body_reads == [] and tasks.pages == []
    assert _rows(replay.path) == before


@pytest.mark.parametrize("native_task", [False, True], ids=["legacy-missing-task", "native-task"])
def test_actual_get_not_ready_is_explicit_without_backfill_or_sql_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_task: bool,
) -> None:
    path, session, _ = _seed_ready_session(tmp_path)
    stores = sqlite_control_plane_stores(path)
    assert stores.sessions.get_session(session) is not None
    if native_task:
        stores.tasks.ensure_for_session(session)  # Admission, not checkpoint preparation.
    else:
        assert stores.tasks.get_task(TaskId(session)) is None
    tasks = ObservationTasks(stores.tasks)
    client = TestClient(
        create_http_app(path, stores=replace(stores, tasks=cast(AgentTaskPort, tasks)))
    )
    before = _rows(path)
    with monkeypatch.context() as patch:
        sql = _SqlObservation(patch, path, bodies=False)
        response = client.get(_stream_path(session, "legacy"))
        assert sql.writes == [] and sql.body_reads == [] and tasks.pages == []
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "projection_not_ready"
        assert response.json()["retryable"] is True
        assert sql.writes == [] and sql.body_reads == [] and tasks.pages == []
    assert _rows(path) == before


def test_actual_get_preflight_is_body_free_before_its_bounded_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = _closed_run(tmp_path)
    tasks = ObservationTasks(replay.stores.tasks)
    stores = replace(replay.stores, tasks=cast(AgentTaskPort, tasks))
    client = TestClient(create_http_app(replay.path, stores=stores))
    before = _rows(replay.path)
    original = ag_ui_stream.prepare_agui_stream
    with monkeypatch.context() as patch:
        sql = _SqlObservation(patch, replay.path, bodies=False)

        def preflight(
            stores: ControlPlaneStores,
            path: str,
            query: Mapping[str, str],
            **kwargs: Any,
        ) -> ag_ui_stream.AgUiStreamContext | ApiResponse | None:
            result = original(stores, path, query, **kwargs)
            assert isinstance(result, ag_ui_stream.AgUiStreamContext)
            assert sql.body_reads == [] and sql.writes == [] and tasks.pages == []
            sql.bodies, tasks.allow_bodies = True, True
            return result

        patch.setattr(stream_v2_http, "prepare_agui_stream", preflight)
        response = client.get(_stream_path(replay.session, "run-1"))
        assert response.status_code == 200 and "RUN_FINISHED" in response.text
        assert sql.writes == [] and len(tasks.pages) == 1
        sql.assert_bounded_body_seeks(pages=1)
    assert _rows(replay.path) == before


def test_actual_get_frames_use_canonical_coordinates_across_a_fractured_derived_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = _closed_run(tmp_path)
    context = _context(replay)
    oracle = [
        encoded
        for _, encoded in ag_ui_stream._project_new_task_events(
            replay.events, context.identity, None
        )
    ]
    assert len(oracle) == 7  # Bootstrap already started this Segment before the Run window.
    with sqlite3.connect(replay.path) as connection:
        connection.execute(
            "DELETE FROM task_event_index WHERE event_id = ?", (str(replay.message.event_id),)
        )
    tasks = ObservationTasks(replay.stores.tasks)
    tasks.allow_bodies = True
    stores = replace(replay.stores, tasks=cast(AgentTaskPort, tasks))
    client = TestClient(create_http_app(replay.path, stores=stores))
    before = _rows(replay.path)
    with monkeypatch.context() as patch:
        sql = _SqlObservation(patch, replay.path, bodies=True)
        response = client.get(_stream_path(replay.session, "run-1"))
        assert response.status_code == 200
        frames = [block + "\n\n" for block in response.text.split("\n\n") if block]
        assert frames == oracle
        canonical = {entry.task_sequence: str(entry.event.event_id) for entry in replay.events}
        assert all(
            canonical[_cursor(frame).sequence] == _cursor(frame).event_id for frame in frames
        )
        assert any(_cursor(frame).event_id == str(replay.message.event_id) for frame in frames)
        assert sql.writes == [] and sql.body_reads and len(tasks.pages) == 1
        sql.assert_bounded_body_seeks(pages=1)
    assert _rows(replay.path) == before


def test_whole_cursor_needs_canonical_source_but_not_a_frame_header(tmp_path: Path) -> None:
    replay = _closed_run(tmp_path, messages=3)
    message = replay.events[replay.command.sequence + 1]
    with sqlite3.connect(replay.path) as connection:
        connection.execute(
            "DELETE FROM task_projection_frames WHERE task_id = ? AND task_sequence = ?",
            (str(replay.session), message.task_sequence),
        )
    whole = AgUiCursor(
        thread_id=str(replay.session),
        run_id="run-1",
        sequence=message.task_sequence,
        event_id=str(message.event.event_id),
    )
    assert _context(replay, whole.encode()).cursor == whole
    partial = ag_ui_stream.prepare_agui_stream(
        replay.stores,
        _stream_path(replay.session, "run-1"),
        {"cursor": whole.model_copy(update={"frame_index": 0}).encode()},
    )
    forged = ag_ui_stream.prepare_agui_stream(
        replay.stores,
        _stream_path(replay.session, "run-1"),
        {"cursor": whole.model_copy(update={"event_id": str(uuid4())}).encode()},
    )
    assert isinstance(partial, ApiResponse) and partial.status_code == 409
    assert partial.body["code"] == "projection_not_ready"
    assert isinstance(forged, ApiResponse) and forged.status_code == 400


@pytest.mark.parametrize("cancel", [False, True])
def test_true_observer_every_frame_disconnect_and_eof_suffix_parity(
    tmp_path: Path,
    cancel: bool,
) -> None:
    replay = _closed_run(tmp_path)
    context = _context(replay)
    expected = [
        encoded
        for _, encoded in ag_ui_stream._project_new_task_events(
            replay.events, context.identity, None
        )
    ]
    assert len(expected) == 7
    cancellation = asyncio.CancelledError("client disconnected")

    class Request(_FakeRequest):
        async def is_disconnected(self) -> bool:
            if self.disconnected and cancel:
                raise cancellation
            return self.disconnected

    async def check() -> None:
        assert await _collect(context) == expected
        for cut in range(1, len(expected) + 1):
            request = Request()
            stream = _stream(_context(replay), request)
            try:
                prefix = [await asyncio.wait_for(anext(stream), 1) for _ in range(cut)]
                assert prefix == expected[:cut]
                request.disconnected = True
                with pytest.raises(
                    asyncio.CancelledError if cancel else StopAsyncIteration
                ) as error:
                    await asyncio.wait_for(anext(stream), 1)
                if cancel:
                    assert error.value is cancellation
            finally:
                await stream.aclose()
            suffix = await _collect(_context(replay, _cursor(prefix[-1]).encode()))
            assert prefix + suffix == expected
        assert await _collect(_context(replay, _cursor(expected[-1]).encode())) == []

    asyncio.run(check())


def test_true_observer_every_frame_reconnect_and_eof_parity(tmp_path: Path) -> None:
    replay = _closed_run(tmp_path)
    context = _context(replay)
    oracle = [
        encoded
        for _, encoded in ag_ui_stream._project_new_task_events(
            replay.events, context.identity, None
        )
    ]
    client = TestClient(create_http_app(replay.path, stores=replay.stores))

    async def check() -> None:
        expected = await _collect(context)
        assert expected == oracle and len(expected) == 7
        for cut in range(1, len(expected) + 1):
            request = _FakeRequest()
            stream = _stream(_context(replay), request)
            try:
                prefix = [await asyncio.wait_for(anext(stream), 1) for _ in range(cut)]
                request.disconnected = True
            finally:
                await stream.aclose()  # Simulate connection cancellation at this exact frame.
            cursor = _cursor(prefix[-1]).encode()
            assert prefix + await _collect(_context(replay, cursor)) == expected
            response = await asyncio.to_thread(
                client.get,
                _stream_path(replay.session, "run-1"),
                params={"cursor": cursor},
            )
            assert response.status_code == 200
            assert response.text == "".join(expected[cut:])

    asyncio.run(check())


def test_run_stop_excludes_new_run_and_late_parent_append(tmp_path: Path) -> None:
    path, session, start = _seed_ready_session(tmp_path)
    source = SQLiteEventStore(path)
    _append(
        source, session, start, EventType.SESSION_COMMAND_ACCEPTED, {"payload": {"run_id": "run-1"}}
    )
    _append(
        source,
        session,
        start + 1,
        EventType.MODEL_RESPONSE_RECEIVED,
        {"model_call_id": "old", "assistant_message": "old answer"},
    )
    stores = checkpoint_stores(path, session, "run-1")
    context = ag_ui_stream.prepare_agui_stream(stores, _stream_path(session, "run-1"), {})
    assert isinstance(context, ag_ui_stream.AgUiStreamContext)

    async def check() -> str:
        stream = ag_ui_stream.tail_agui_events(context, _FakeRequest())
        first = await asyncio.wait_for(anext(stream), 1)
        new_run = _append(
            source,
            session,
            start + 2,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"payload": {"run_id": "run-2"}},
        )
        _append(
            source,
            session,
            start + 3,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "late-parent", "assistant_message": "new-run-only"},
        )
        _append(source, session, start + 4, EventType.SESSION_COMPLETED, {})
        checkpoint_stores(path, session, "run-1")  # External materializer, not GET maintenance.
        checkpoint_stores(path, session, "run-2")
        async with asyncio.timeout(2):
            frames = [first, *[frame async for frame in stream]]
        assert all(_cursor(frame).sequence < new_run.sequence for frame in frames)
        return "".join(frames)

    output = asyncio.run(check())
    assert "old answer" in output and "new-run-only" not in output and "RUN_FINISHED" not in output
    client = TestClient(create_http_app(path, stores=stores))
    response = client.get(_stream_path(session, "run-2"))
    assert response.status_code == 200 and "new-run-only" in response.text
    assert "old answer" not in response.text and "RUN_FINISHED" in response.text


def test_disconnected_observer_reads_no_pages_and_expired_observer_emits_no_frames(
    tmp_path: Path,
) -> None:
    replay = _closed_run(tmp_path)
    tasks = ObservationTasks(replay.stores.tasks)
    stores = replace(replay.stores, tasks=cast(AgentTaskPort, tasks))
    context = ag_ui_stream.prepare_agui_stream(stores, _stream_path(replay.session, "run-1"), {})
    assert isinstance(context, ag_ui_stream.AgUiStreamContext)

    async def check() -> None:
        request = _FakeRequest()
        request.disconnected = True
        assert [frame async for frame in ag_ui_stream.tail_agui_events(context, request)] == []
        expired = replace(
            context, authorization_expires_at=datetime.now(UTC) - timedelta(seconds=1)
        )
        assert await _collect(expired) == []

    asyncio.run(check())
    assert tasks.pages == []


@pytest.mark.parametrize("operation", ["metadata", "page"])
@pytest.mark.parametrize("stop", ["expire", "cancel", "disconnect"])
def test_slow_metadata_read_does_not_outlive_authorization_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    stop: str,
) -> None:
    replay = _closed_run(tmp_path)
    context = replace(
        _context(replay),
        authorization_expires_at=datetime.now(UTC)
        + timedelta(seconds=0.06 if stop == "expire" else 1),
    )
    entered, release, finished = Event(), Event(), Event()
    snapshot = AgUiCheckpointObserver.snapshot
    read_page = AgUiCheckpointObserver.read_page

    def slow_snapshot(
        self: AgUiCheckpointObserver,
        task: TaskId,
        identity: AgUiRunIdentity,
    ) -> AgUiObservationSnapshot:
        entered.set()
        try:
            assert release.wait(1), "probe cleanup must release the scratch read"
            return snapshot(self, task, identity)
        finally:
            finished.set()

    def slow_page(
        self: AgUiCheckpointObserver,
        snapshot: AgUiObservationSnapshot,
        after: int,
    ) -> TaskEventPage | None:
        entered.set()
        try:
            assert release.wait(1), "probe cleanup must release the scratch read"
            return read_page(self, snapshot, after)
        finally:
            finished.set()

    if operation == "metadata":
        monkeypatch.setattr(AgUiCheckpointObserver, "snapshot", slow_snapshot)
    else:
        monkeypatch.setattr(AgUiCheckpointObserver, "read_page", slow_page)

    async def check() -> None:
        request = _FakeRequest()
        stream = _stream(context, request)
        started = monotonic()
        try:
            pending = asyncio.ensure_future(anext(stream))
            assert await asyncio.to_thread(entered.wait, 0.1)
            if stop == "cancel":
                pending.cancel()
            elif stop == "disconnect":
                request.disconnected = True
                release.set()
            with pytest.raises(asyncio.CancelledError if stop == "cancel" else StopAsyncIteration):
                await asyncio.wait_for(pending, 0.20)
            assert entered.is_set() and monotonic() - started < 0.20
        finally:
            release.set()
            await stream.aclose()
            assert await asyncio.to_thread(finished.wait, 0.5)

    asyncio.run(check())


@pytest.mark.parametrize("inner_error", [TimeoutError, asyncio.CancelledError])
def test_shared_deadline_preserves_inner_error_and_closes_source(
    inner_error: type[BaseException],
) -> None:
    closed: list[bool] = []

    async def source() -> AsyncGenerator[str, None]:
        try:
            yield "first"
            raise inner_error("inner failure, not the authorization deadline")
        finally:
            closed.append(True)

    async def check() -> None:
        frames = deadline_frames(source(), monotonic() + 1)
        assert await anext(frames) == "first"
        with pytest.raises(inner_error, match="inner failure"):
            await anext(frames)
        assert closed == [True]

    asyncio.run(check())


@pytest.mark.parametrize("cancel", [False, True])
def test_shared_deadline_closes_blocked_source_on_expiry_or_external_cancel(cancel: bool) -> None:
    async def check() -> None:
        entered, blocked, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def source() -> AsyncGenerator[str, None]:
            try:
                entered.set()
                await blocked.wait()
                yield "must never emit"
            finally:
                closed.set()

        frames = deadline_frames(source(), monotonic() + (1 if cancel else 0.04))
        pending = asyncio.ensure_future(anext(frames))
        await asyncio.wait_for(entered.wait(), 0.2)
        if cancel:
            pending.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else StopAsyncIteration):
            await asyncio.wait_for(pending, 0.2)
        assert closed.is_set() and not blocked.is_set()

    asyncio.run(check())


def test_observer_backpressure_close_releases_its_one_page_and_stops_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = _closed_run(tmp_path, messages=300)
    tasks = ObservationTasks(replay.stores.tasks)
    tasks.allow_bodies = True
    stores = replace(replay.stores, tasks=cast(AgentTaskPort, tasks))
    context = ag_ui_stream.prepare_agui_stream(stores, _stream_path(replay.session, "run-1"), {})
    assert isinstance(context, ag_ui_stream.AgUiStreamContext)
    references: list[ReferenceType[SessionEvent]] = []
    read_page = tasks.read_event_page

    def page(task: TaskId, after: int, **kwargs: Any) -> TaskEventPage:
        result = read_page(task, after, **kwargs)
        references.extend(ref(entry.event) for entry in result.events)
        return result

    monkeypatch.setattr(tasks, "read_event_page", page)

    async def check() -> None:
        stream = _stream(context, _FakeRequest())
        try:
            first = await asyncio.wait_for(anext(stream), 1)
            assert _cursor(first).sequence == replay.command.sequence + 1
            await asyncio.sleep(0.04)  # Consumer backpressure must not start Page two.
            assert len(tasks.pages) == 1 and tasks.page_sizes[0][0] == 256
            assert references and any(reference() is not None for reference in references)
        finally:
            await stream.aclose()
        await asyncio.sleep(0.04)
        assert len(tasks.pages) == 1
        assert all(reference() is None for reference in references), (
            "closed stream retained Event bodies"
        )

    asyncio.run(check())


def test_actual_get_large_backlog_reads_only_bounded_pages_and_never_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = _closed_run(tmp_path, messages=300)
    tasks = ObservationTasks(replay.stores.tasks)
    tasks.allow_bodies = True
    stores = replace(replay.stores, tasks=cast(AgentTaskPort, tasks))
    client = TestClient(create_http_app(replay.path, stores=stores))
    before = _rows(replay.path)
    with monkeypatch.context() as patch:
        sql = _SqlObservation(patch, replay.path, bodies=True)
        response = client.get(_stream_path(replay.session, "run-1"))
        assert response.status_code == 200 and "RUN_FINISHED" in response.text
        frames = [block for block in response.text.split("\n\n") if block.startswith("id: ")]
        assert len(frames) == 901  # 300 distinct Start/Content/End + RunFinished, bootstrap primed.
        assert len(tasks.pages) == 2
        assert all(limit <= 256 and budget <= 1_048_576 for _, limit, budget in tasks.pages)
        assert [count for count, _ in tasks.page_sizes] == [256, 46]
        assert sql.writes == [] and sql.body_reads
        sql.assert_bounded_body_seeks(pages=2)
    assert _rows(replay.path) == before


@pytest.mark.parametrize("existing_run", [False, True], ids=["new-run", "discover-existing-run"])
def test_production_worker_prepares_get_replay_without_checkpoint_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_run: bool,
) -> None:
    from zebra_agent_worker import build_worker_loop_service

    from tests.api.test_agui_command_routes import _run_input
    from tests.worker.execution.worker_execution_support import (
        _assistant_only_gateway,
        _settings,
    )

    path, session, next_sequence = _seed_ready_session(tmp_path)
    stores = sqlite_control_plane_stores(path)
    stores.tasks.ensure_for_session(session)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    loop = build_worker_loop_service(
        database_path=path,
        settings=_settings(path),
        stores=stores,
    )
    client = TestClient(create_http_app(path, stores=stores))
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM task_projection_work_projectors WHERE enabled=1"
            ).fetchone()[0]
            == 0
        )
    try:
        assert loop._projection_work is not None, (
            "production Worker has no projection-work composition"
        )
        if not existing_run:
            loop.maintenance_once(
                worker_id="checkpoint-get-quality", batch_size=1, lease_ttl_seconds=30
            )
        accepted = client.post(
            "/agui/commands",
            headers={"Idempotency-Key": "checkpoint-get-quality"},
            json={
                "action": "run",
                "threadId": str(session),
                "runId": "run-1",
                "expectedRevision": next_sequence - 1,
                "input": _run_input(session, "run-1"),
            },
        )
        assert accepted.status_code == 202, accepted.text
        if existing_run:
            loop.maintenance_once(
                worker_id="checkpoint-get-quality", batch_size=1, lease_ttl_seconds=30
            )
        executed = loop.poll_once(worker_id="checkpoint-get-quality")
        assert executed.executed_session_ids == (str(session),)
        deadline = monotonic() + 3
        while True:
            try:
                run = stores.tasks.read_run_header(TaskId(session), "run-1")
                assert run.anchor is not None
                scope = ProjectionScope(
                    "local", TaskId(session), run.anchor.event_id, AG_UI_CHECKPOINT_VERSION
                )
                if stores.tasks.read_checkpoint_head(scope).through_sequence == run.highwater:
                    break
            except CheckpointNotReady:
                pass
            assert monotonic() < deadline, "production Worker never published the source frontier"
            sleep(0.01)
    finally:
        loop.drain()  # All producer writes stop before the GET SQL guard below.
    before = _rows(path)
    with monkeypatch.context() as patch:
        sql = _SqlObservation(patch, path, bodies=True)
        response = client.get(_stream_path(session, "run-1"))
        assert response.status_code == 200, response.text
        assert "Worker completed the session." in response.text and "RUN_FINISHED" in response.text
        assert sql.writes == []
    assert _rows(path) == before
