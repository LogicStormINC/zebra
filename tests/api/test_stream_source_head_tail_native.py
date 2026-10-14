"""Source-head tail scheduling preserves terminal drain and fresh privacy."""

import asyncio
from pathlib import Path

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from zebra_agent_api.session_streaming import StreamWake, tail_session_events, tail_task_events

from tests.api.test_cloud_stream_read_bounds import append
from tests.api.test_cloud_stream_read_bounds import postgres_dsn as _dsn_fixture
from tests.api.test_cloud_stream_read_bounds import source as _source_fixture
from tests.api.test_cloud_stream_read_bounds import task_namespace as _namespace_fixture
from tests.worker.test_transient_output_composition_native import owned as _owned_fixture

postgres_dsn = _dsn_fixture
source = _source_fixture
task_namespace = _namespace_fixture


class Connected:
    async def is_disconnected(self):
        return False


@pytest.mark.parametrize("reader", ["session", "task"])
def test_terminal_commit_after_quiet_head_is_drained(source, monkeypatch, reader):
    stores, sid = source
    append(source, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    cursor = stores.tasks.read_stream_source_head(task_id=TaskId(sid)).task.current_sequence
    original = stores.tasks.read_stream_source_head
    committed = False

    def read(**kwargs):
        nonlocal committed
        head = original(**kwargs)
        if not committed:
            committed = True
            append(source, EventType.SESSION_COMPLETED, {"summary": "done", "metadata": {}})
        return head

    async def wake(*args, **kwargs):
        return True

    monkeypatch.setattr(stores.tasks, "read_stream_source_head", read)
    monkeypatch.setattr(StreamWake, "wait", wake)
    tail = tail_session_events if reader == "session" else tail_task_events

    async def collect():
        return [
            frame
            async for frame in tail(
                database_path=Path("/unused"),
                stores=stores,
                request=Connected(),
                after_sequence=cursor,
                **({"session_id": sid} if reader == "session" else {"task_id": TaskId(sid)}),
            )
        ]

    frames = asyncio.run(asyncio.wait_for(collect(), 5))
    assert committed and any("session_completed" in frame for frame in frames)


@pytest.mark.parametrize("reader", ["session", "task"])
def test_privacy_append_after_head_denies_changed_page(source, monkeypatch, reader):
    stores, sid = source
    cursor = stores.tasks.read_stream_source_head(task_id=TaskId(sid)).task.current_sequence
    append(source, EventType.MODEL_RESPONSE_DELTA, {"content_delta": "private"})
    owner = stores.events if reader == "session" else stores.tasks
    method = "read_session_event_page" if reader == "session" else "read_event_page"
    original = getattr(owner, method)

    def read(*args, **kwargs):
        page = original(*args, **kwargs)
        append(source, EventType.COVERAGE_BATCH_ACCEPTED, {})
        return page

    monkeypatch.setattr(owner, method, read)
    tail = tail_session_events if reader == "session" else tail_task_events

    async def collect():
        return [
            frame
            async for frame in tail(
                database_path=Path("/unused"),
                stores=stores,
                request=Connected(),
                after_sequence=cursor,
                **({"session_id": sid} if reader == "session" else {"task_id": TaskId(sid)}),
            )
        ]

    assert asyncio.run(asyncio.wait_for(collect(), 5)) == []


owned = _owned_fixture


def test_blackhole_recovery_reports_actual_read_phases(
    owned, monkeypatch, tmp_path, record_property
):
    from collections import Counter
    from time import monotonic

    from agent_integrations.redis_live_fanout_async import AsyncRedisNotifications
    from zebra_agent_api import ag_ui_checkpoint_tail, stream_v2_reader

    from tests.api import test_stream_v2_native as original_case
    from tests.stream_storage.telemetry import Telemetry

    phases, counts, clocks, barriers = Counter(), Counter(), [], []
    telemetry = Telemetry()
    actual_barrier = AsyncRedisNotifications.barrier

    async def barrier(self, key):
        started = monotonic()
        try:
            return await actual_barrier(self, key)
        finally:
            barriers.append(monotonic() - started)

    monkeypatch.setattr(AsyncRedisNotifications, "barrier", barrier)

    async def measured(deadline, read, *args, **kwargs):
        started = monotonic()
        name = getattr(read, "__name__", type(read).__name__)
        try:
            return await real_read(deadline, read, *args, **kwargs)
        finally:
            phases[name] += monotonic() - started
            counts[name] += 1

    real_read = ag_ui_checkpoint_tail._read_until
    monkeypatch.setattr(ag_ui_checkpoint_tail, "_read_until", measured)
    monkeypatch.setattr(stream_v2_reader, "_read_until", measured)

    def clock():
        value = monotonic()
        clocks.append(value)
        telemetry.stage = "recovery" if len(clocks) == 1 else "complete"
        return value

    monkeypatch.setattr(original_case, "monotonic", clock)
    with telemetry.installed():
        original_case.test_native_blackhole_startup_budget_preserves_durable_recovery(
            owned, monkeypatch, tmp_path, "agui"
        )
    assert len(clocks) == 2
    record_property("recovery_seconds", clocks[1] - clocks[0])
    record_property("read_phase_seconds", dict(phases))
    record_property("read_phase_counts", dict(counts))
    record_property("async_barrier_seconds", barriers)
    record_property(
        "recovery_client_sql",
        sum(
            count
            for name, count in telemetry.calls.items()
            if name.startswith("recovery/") and "/sql:" in name
        ),
    )


@pytest.mark.parametrize("outcome_kind", ["plain", "native-class", "native-wraps"])
def test_custom_outcome_callable_is_preserved_with_native_head_store(
    source, record_property, monkeypatch, outcome_kind,
):
    from functools import wraps
    from time import monotonic
    from types import SimpleNamespace

    from agent_integrations.ag_ui.contracts import AgUiRunIdentity
    from agent_storage.postgres.command_wakeup_outcome import PostgresCommandOutcomeReader
    from zebra_agent_api.ag_ui_checkpoint_tail import tail_checkpoint_frames
    from zebra_agent_api.ag_ui_stream import AgUiStreamContext

    from tests.agent_storage.test_stream_source_head_native import checkpoint_source

    stores, sid, run, _scope = checkpoint_source(source)
    stores.projection_work = stores.coverage_projection_work = None
    calls = []

    def custom(task_id, run_id, accepted, host):
        calls.append((task_id, run_id, accepted, host))
        return "command_unsupported"

    native = PostgresCommandOutcomeReader(
        stores.tasks._database._dsn, deployment_namespace=stores.deployment_namespace,
    )
    assert native.supports_source_head(stores.tasks)
    outcome = custom
    if outcome_kind != "plain":
        def override(self, *args):
            return custom(*args)

        if outcome_kind == "native-wraps":
            override = wraps(PostgresCommandOutcomeReader.__call__)(override)
        monkeypatch.setattr(PostgresCommandOutcomeReader, "__call__", override)
        assert not native.supports_source_head(stores.tasks)
        outcome = native

    host = SimpleNamespace()
    context = AgUiStreamContext(
        stores,
        TaskId(sid),
        AgUiRunIdentity(session_id=sid, thread_id=str(sid), run_id="run"),
        None,
        deployment_namespace=stores.deployment_namespace,
        command_outcome=outcome,
        host_context=host,
    )

    async def collect():
        return [
            frame
            async for frame in tail_checkpoint_frames(
                context, Connected(), monotonic() + 3, poll_seconds=0.01, keepalive_seconds=0.1
            )
        ]

    frames = asyncio.run(collect())
    record_property("notice_conflict", any("projection_conflict" in frame for frame in frames))
    record_property(
        "notice_unavailable", any("observation_unavailable" in frame for frame in frames)
    )
    assert calls == [(TaskId(sid), "run", run.anchor.event_id, host)]
    assert any("command_unsupported" in frame for frame in frames)


def test_agui_initial_snapshot_one_socket_and_native_override_fallback(owned, monkeypatch):
    from dataclasses import make_dataclass, replace
    from datetime import UTC, datetime, timedelta
    from functools import wraps
    from time import monotonic
    from types import SimpleNamespace

    from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
    from agent_storage import with_committed_event_publisher
    from agent_storage.postgres.direct_control import PostgresDirectControl
    from zebra_agent_api import stream_v2_http

    from tests.api.test_stream_v2_native import materialize, opened
    from tests.stream_storage import native_environment
    from tests.stream_storage.telemetry import Telemetry
    from tests.worker.test_task_binding_host_context import _context

    bootstrap = native_environment.SessionBootstrapCommand
    monkeypatch.setattr(
        native_environment,
        "SessionBootstrapCommand",
        lambda **kw: bootstrap(host_context=_context(), **kw),
    )
    run, writer, response, reader, bound, recovery = opened(owned, monkeypatch, frames=1)
    from agent_core.harness.orchestration_events import model_response_event

    recovery.persist_with(run.recorder.append_draft)(
        model_response_event(response, attempt_number=1, response_stage="candidate")
    )
    materialize(run.stores, run.task_id, owned)
    run.stores.deployment_namespace = run.namespace
    bundle = make_dataclass("ReadStores", [(key, object) for key in vars(run.stores)])(
        **vars(run.stores)
    )
    api = SimpleNamespace(
        stores=with_committed_event_publisher(
            bundle, SimpleNamespace(publish_committed=lambda _: None)
        ),
        stream_v2_reader=reader,
        cloud_control=PostgresDirectControl(owned[0], deployment_namespace=run.namespace),
        live_event_fanout=None,
        command_outcome=None,
        stream_notifications=None,
    )
    # Actual factory replacement keeps the native Task adapter, not bundle identity.
    assert api.stores is not reader.authority.stores
    host = bound.host
    from agent_storage.postgres.stream_proof_batch import StreamProofSnapshot

    qualified_calls, head_calls = [], []
    original_header = StreamProofSnapshot.read_task_header
    original_head = StreamProofSnapshot.read_stream_checkpoint_head

    def header(proof, task_id, **kwargs):
        qualified_calls.append(kwargs.get("require_source_coverage", False))
        return original_header(proof, task_id, **kwargs)

    def checkpoint_head(proof, *args, **kwargs):
        head_calls.append(True)
        return original_head(proof, *args, **kwargs)

    monkeypatch.setattr(StreamProofSnapshot, "read_task_header", header)
    monkeypatch.setattr(StreamProofSnapshot, "read_stream_checkpoint_head", checkpoint_head)

    def request(query=None):
        return SimpleNamespace(
            state=SimpleNamespace(host_context=host, authorization_deadline=monotonic() + 2),
            query_params=query or {},
            headers={},
            url=SimpleNamespace(path=f"/agui/threads/{run.task_id}/runs/run-v2/stream"),
            is_disconnected=Connected().is_disconnected,
        )

    try:
        telemetry = Telemetry()
        with telemetry.installed():
            response = asyncio.run(stream_v2_http.agui_response(api, request()))
        assert response.status_code == 200
        assert qualified_calls == [True, False] and len(head_calls) == 1
        expired = request()
        expired.state.host_context = host.model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
        assert asyncio.run(stream_v2_http.agui_response(api, expired)).status_code == 403
        assert sum(v for k, v in telemetry.calls.items() if k.endswith("/new_pg_socket")) == 1
        from agent_integrations.ag_ui import AgUiCursor, AgUiRunIdentity
        from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver

        identity = AgUiRunIdentity(
            session_id=run.session_id, thread_id=str(run.task_id), run_id="run-v2"
        )
        snapshot = AgUiCheckpointObserver(api.stores.tasks, namespace=run.namespace).snapshot(
            run.task_id, identity
        )
        framed = next(
            frame
            for sequence in range(snapshot.run.start, snapshot.run.highwater + 1)
            if (
                frame := api.stores.tasks.read_event_projection_header(
                    snapshot.head.scope, sequence
                )
            )
            is not None
            and frame.frame_count > 0
        )
        cursor = AgUiCursor(
            thread_id=identity.thread_id,
            run_id=identity.run_id,
            sequence=framed.task_sequence,
            event_id=str(framed.event_id),
            frame_index=0,
        )
        context = reader.context(bound, kind="agui", token=None, full_recovery=False)

        def signed(cursor):
            return reader.codec.encode(replace(context.cursor, durable=cursor.encode()))

        telemetry = Telemetry()
        with telemetry.installed():
            partial = asyncio.run(
                stream_v2_http.agui_response(api, request({"cursor": signed(cursor)}))
            )
        assert partial.status_code == 200
        assert qualified_calls[-2:] == [True, False] and len(head_calls) == 2
        assert sum(v for k, v in telemetry.calls.items() if k.endswith("/new_pg_socket")) == 1
        future = cursor.model_copy(update={"sequence": snapshot.run.highwater + 1})
        assert (
            asyncio.run(
                stream_v2_http.agui_response(api, request({"cursor": signed(future)}))
            ).status_code
            == 400
        )
        for target, name, expected in (
            (api.stores.tasks, "read_task_header", 404),
            (api.stores.tasks, "read_stream_checkpoint_head", 409),
            (api.stores.tasks, "read_run_header", 409),
            (api.stores.tasks, "read_checkpoint_head", 409),
            (api.stores.tasks, "read_event_header", 400),
            (api.stores.tasks, "read_event_projection_header", 409),
            (reader.authority, "bind", 200),
            (reader.authority, "bind_snapshot", 200),
            (stream_v2_http, "prepare_agui_stream", 409),
        ):
            for class_hook in (False, True) if target is not stream_v2_http else (False,):
                invoked = []
                original = getattr(target, name)

                @wraps(original)
                def custom(*args, _name=name, _invoked=invoked, **kwargs):
                    _invoked.append(True)
                    if _name == "read_task_header":
                        assert kwargs["require_source_coverage"] is True
                    if _name in {
                        "read_task_header",
                        "bind",
                        "bind_snapshot",
                        "read_event_header",
                        "read_event_projection_header",
                    }:
                        return None
                    raise CheckpointNotReady("custom reader denies readiness")

                # Callback keeps its original response contract rather than raising.
                if target is stream_v2_http:
                    from zebra_agent_api.responses import ApiResponse

                    def custom(*args, _invoked=invoked, **kwargs):
                        _invoked.append(True)
                        return ApiResponse(409, {"status": "custom_denial"})

                legacy_flags = []
                with monkeypatch.context() as extension:
                    if name in {"bind", "bind_snapshot"}:
                        actual_header = api.stores.tasks.read_task_header

                        def legacy_header(
                            *args, _flags=legacy_flags, _read=actual_header, **kwargs
                        ):
                            _flags.append(kwargs["require_source_coverage"])
                            return _read(*args, **kwargs)

                        extension.setitem(vars(api.stores.tasks), "read_task_header", legacy_header)
                    if class_hook:
                        extension.setattr(type(target), name, custom)
                    else:
                        extension.setitem(vars(target), name, custom)
                    assert stream_v2_http._agui_snapshot_authority(api) is None
                    result = asyncio.run(
                        stream_v2_http.agui_response(
                            api,
                            request({"cursor": signed(cursor)})
                            if name.startswith("read_event")
                            else request(),
                        )
                    )
                    assert result.status_code == expected and invoked
                    if name in {"bind", "bind_snapshot"}:
                        assert legacy_flags == [True]
        from zebra_agent_api.coverage_public_read import cloud_raw_stream_preflight

        api.settings = SimpleNamespace(deployment="cloud")
        for name, route, expected in (
            ("task_id_for_session", "session", 409),
            ("read_latest_run_header", "task", 409),
            ("read_task_header", "task", 409),
            ("read_task_header", "session", 409),
            ("bind", "task", None),
            ("bind_snapshot", "task", None),
        ):
            target = reader.authority if name.startswith("bind") else api.stores.tasks
            for class_hook in (False, True):
                original = getattr(target, name)
                invoked = []

                @wraps(original)
                def custom_raw(*args, _name=name, _invoked=invoked, **kwargs):
                    _invoked.append(True)
                    if _name == "read_latest_run_header":
                        raise CheckpointNotReady("custom latest reader denies")
                    return None

                raw_request = request()
                raw_request.url.path = (
                    f"/sessions/{run.session_id}/stream"
                    if route == "session"
                    else f"/tasks/{run.task_id}/stream"
                )

                def preflight(proof=None, _path=raw_request.url.path):
                    result = cloud_raw_stream_preflight(api.stores, _path, proof=proof)
                    return result if result.status_code != 200 else None

                with monkeypatch.context() as extension:
                    if class_hook:
                        extension.setattr(type(target), name, custom_raw)
                    else:
                        extension.setitem(vars(target), name, custom_raw)
                    assert stream_v2_http._native_raw_authority(api) is None
                    result = asyncio.run(
                        stream_v2_http.raw_response(
                            api,
                            raw_request,
                            database_path=Path("/unused"),
                            preflight=preflight,
                            snapshot_preflight=preflight,
                        )
                    )
                    assert (getattr(result, "status_code", None) == expected) and invoked
        from zebra_agent_api.responses import ApiResponse

        for route in ("session", "task"):
            callback_calls = []
            original_prepare = stream_v2_http.prepare_v2

            @wraps(original_prepare)
            def old_callback(api_arg, path, query, host_arg, _calls=callback_calls):
                _calls.append((api_arg, path, query, host_arg))
                return ApiResponse(409, {"status": "custom_prepare_denied"})

            callback_request = request()
            callback_request.url.path = (
                f"/sessions/{run.session_id}/stream"
                if route == "session"
                else f"/tasks/{run.task_id}/stream"
            )

            def callback_preflight(proof=None, _path=callback_request.url.path):
                response = cloud_raw_stream_preflight(api.stores, _path, proof=proof)
                return response if response.status_code != 200 else None

            with monkeypatch.context() as extension:
                extension.setattr(stream_v2_http, "prepare_v2", old_callback)
                assert stream_v2_http._raw_snapshot_authority(api) is None
                result = asyncio.run(
                    stream_v2_http.raw_response(
                        api,
                        callback_request,
                        database_path=Path("/unused"),
                        preflight=callback_preflight,
                        snapshot_preflight=callback_preflight,
                    )
                )
            assert (
                result.status_code == 409 and result.body == b'{"status":"custom_prepare_denied"}'
            )
            assert len(callback_calls) == 1 and callback_calls[0][0] is api
        observer = AgUiCheckpointObserver(api.stores.tasks, namespace=run.namespace)
        page = observer.read_page(snapshot, framed.task_sequence - 1)
        assert page is not None
        for name in (
            "read_event_projection_header",
            "read_segment_checkpoint_before",
            "read_cells_at",
        ):
            for class_hook in (False, True):
                original = getattr(api.stores.tasks, name)
                invoked = []

                @wraps(original)
                def custom_restore(*args, _invoked=invoked, **kwargs):
                    _invoked.append(True)
                    raise CheckpointNotReady("custom restore denies")

                with monkeypatch.context() as extension:
                    if class_hook:
                        extension.setattr(type(api.stores.tasks), name, custom_restore)
                    else:
                        extension.setitem(vars(api.stores.tasks), name, custom_restore)
                    assert not api.stores.tasks.stream_head_reads_compatible
                    with pytest.raises(CheckpointNotReady):
                        list(observer.iter_page_frames(snapshot, page, identity))
                    assert invoked
        from agent_storage.postgres.database import PostgresDatabase

        database = PostgresDatabase(owned[0], deployment_namespace=run.namespace)
        with database.connect() as connection:
            connection.execute(
                "DELETE FROM session_observation_headers "
                "WHERE deployment_namespace=%s AND session_id=%s",
                (run.namespace, str(run.session_id)),
            )
        qualified_calls.clear()
        previous_heads = len(head_calls)
        rejected = asyncio.run(stream_v2_http.agui_response(api, request({"cursor": "malformed"})))
        assert rejected.status_code == 409 and qualified_calls == [True]
        assert rejected.body.find(b"stream_source_unavailable") >= 0
        assert len(head_calls) == previous_heads
        original_bind = reader.authority.bind_snapshot

        @wraps(original_bind)
        def custom_bind(*args, **kwargs):
            return original_bind(*args, **kwargs)

        qualified_calls.clear()
        with monkeypatch.context() as extension:
            extension.setitem(vars(reader.authority), "bind_snapshot", custom_bind)
            fallback = asyncio.run(
                stream_v2_http.agui_response(api, request({"cursor": "malformed"}))
            )
        assert fallback.status_code == rejected.status_code and fallback.body == rejected.body
        assert qualified_calls == [True] and len(head_calls) == previous_heads
    finally:
        writer.close()
        asyncio.run(reader.close())


def test_native_quiet_tails_honor_task_and_publisher_public_read_hooks(source, monkeypatch):
    from functools import wraps
    from types import SimpleNamespace

    from agent_core.domain.sessions import SessionStatus
    from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
    from agent_storage.live_event_store import PostCommitPublishingEventStore

    stores, sid = source
    append(source, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    underlying = stores.events
    stores.events = PostCommitPublishingEventStore(
        underlying, SimpleNamespace(publish_committed=lambda _: None)
    )
    cursor = stores.tasks.read_stream_source_head(session_id=sid).session_sequence

    async def session_frames():
        return [
            frame
            async for frame in tail_session_events(
                database_path=Path("/unused"),
                stores=stores,
                session_id=sid,
                deployment_namespace=stores.deployment_namespace,
                request=Connected(),
                after_sequence=cursor,
            )
        ]

    for target in (stores.events, underlying):
        for name in ("read_session_event_page", "read_session_status"):
            for class_hook in (False, True):
                invoked = []
                original = getattr(target, name)

                @wraps(original)
                def custom(*args, _name=name, _invoked=invoked, **kwargs):
                    _invoked.append(True)
                    if _name == "read_session_status":
                        return SessionStatus.COMPLETED
                    raise CheckpointNotReady("custom Session page denies")

                with monkeypatch.context() as extension:
                    if class_hook:
                        extension.setattr(type(target), name, custom)
                    else:
                        extension.setitem(vars(target), name, custom)
                    assert not stores.events.stream_head_reads_compatible
                    if name == "read_session_status":
                        assert asyncio.run(asyncio.wait_for(session_frames(), 2)) == []
                    else:
                        with pytest.raises(CheckpointNotReady):
                            asyncio.run(asyncio.wait_for(session_frames(), 2))
                    assert invoked
    original = stores.tasks.read_event_page
    for class_hook in (False, True):
        invoked = []

        @wraps(original)
        def custom_page(*args, _invoked=invoked, **kwargs):
            _invoked.append(True)
            raise CheckpointNotReady("custom Task page denies")

        async def task_frames():
            return [
                frame
                async for frame in tail_task_events(
                    database_path=Path("/unused"),
                    stores=stores,
                    task_id=TaskId(sid),
                    deployment_namespace=stores.deployment_namespace,
                    request=Connected(),
                    after_sequence=stores.tasks.read_task_header(TaskId(sid)).current_sequence,
                )
            ]

        with monkeypatch.context() as extension:
            if class_hook:
                extension.setattr(type(stores.tasks), "read_event_page", custom_page)
            else:
                extension.setitem(vars(stores.tasks), "read_event_page", custom_page)
            assert not stores.tasks.stream_head_reads_compatible
            with pytest.raises(CheckpointNotReady):
                asyncio.run(asyncio.wait_for(task_frames(), 2))
            assert invoked
