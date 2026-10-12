from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent_core.domain.identifiers import TaskId
from agent_integrations.ag_ui import AgUiCursor
from zebra_agent_api.stream_v2_cursor import StreamV2Cursor
from zebra_agent_api.stream_v2_http import prepare_v2, source_query

from tests.worker.test_transient_output_composition_native import owned as _owned_fixture

owned = _owned_fixture


@pytest.mark.parametrize("alias", ["cursor", "after", "last_event_id"])
def test_missing_reader_rejects_all_v2_cursor_aliases(alias):
    api = SimpleNamespace(stream_v2_reader=None)
    result = prepare_v2(api, "/tasks/unused/stream", {alias: "v2.token"}, object())
    assert result.status_code == 503


def test_chunk_resume_rewinds_exact_source_frame(monkeypatch):
    source = AgUiCursor(
        thread_id=str(uuid4()), run_id="run", sequence=9, event_id=str(uuid4()), frame_index=3
    )
    context = SimpleNamespace(
        full_recovery=False,
        kind="agui",
        cursor=StreamV2Cursor("scope", source.encode(), chunk_index=4),
    )
    context.binding = SimpleNamespace(
        authority=SimpleNamespace(allowed_session_ids=(str(uuid4()),)),
        namespace="test",
        task_id=TaskId(uuid4()),
        run_id="run",
    )
    monkeypatch.setattr(
        "agent_integrations.ag_ui.checkpoint_observer.AgUiCheckpointObserver",
        lambda *a, **kw: SimpleNamespace(snapshot=lambda *a: None, validate_cursor=lambda *a: None),
    )
    query = source_query(SimpleNamespace(stores=SimpleNamespace(tasks=object())), context, {})
    previous = AgUiCursor.decode(query["cursor"])
    assert previous.sequence == 9 and previous.frame_index == 2
    assert source.frame_index == 3


def test_first_frame_chunk_resume_rewinds_only_one_event(monkeypatch):
    source = AgUiCursor(
        thread_id=str(uuid4()), run_id="run", sequence=9, event_id=str(uuid4()), frame_index=0
    )
    previous = SimpleNamespace(task_sequence=8, event_id=uuid4())
    tasks = SimpleNamespace(
        read_event_header=lambda task, sequence: previous
        if sequence == 8
        else pytest.fail("wrong source")
    )
    context = SimpleNamespace(
        full_recovery=False,
        kind="agui",
        cursor=StreamV2Cursor("scope", source.encode(), chunk_index=4),
        binding=SimpleNamespace(task_id=TaskId(uuid4())),
    )
    context.binding.authority = SimpleNamespace(allowed_session_ids=(str(uuid4()),))
    context.binding.namespace, context.binding.run_id = "test", "run"
    monkeypatch.setattr(
        "agent_integrations.ag_ui.checkpoint_observer.AgUiCheckpointObserver",
        lambda *a, **kw: SimpleNamespace(snapshot=lambda *a: None, validate_cursor=lambda *a: None),
    )
    query = source_query(SimpleNamespace(stores=SimpleNamespace(tasks=tasks)), context, {})
    restored = AgUiCursor.decode(query["cursor"])
    assert restored.sequence == 8 and restored.frame_index is None


def test_cloud_factory_cannot_enable_unreadable_new_v2(tmp_path):
    from dataclasses import replace

    from zebra_agent_api.factory import create_app
    from zebra_agent_config.stream_settings import StreamSettings

    from tests.api.test_host_auth_http import _cloud_settings

    settings = replace(
        _cloud_settings("postgresql://unused.invalid/zebra"), stream=StreamSettings(True)
    )
    with pytest.raises(ValueError, match="shared cursor key"):
        create_app(tmp_path / "unused", settings=settings)


@pytest.mark.parametrize("route", ["session", "task"])
def test_configured_reader_keeps_unstarted_task_legacy_without_hiding_broken_run(route):
    from agent_core.domain.events import EventType
    from agent_core.ports.task_projection_checkpoints import CheckpointNotReady

    task_id, session_id = TaskId(uuid4()), uuid4()
    events = []

    def latest(_task):
        raise CheckpointNotReady("no executable Run")

    tasks = SimpleNamespace(
        task_id_for_session=lambda _: task_id,
        read_latest_run_header=latest,
        read_event_page=lambda *a, **kw: SimpleNamespace(events=events, has_more=False),
    )
    api = SimpleNamespace(
        stream_v2_reader=object(), stores=SimpleNamespace(tasks=tasks, deployment_namespace="owned")
    )
    path = f"/sessions/{session_id}/stream" if route == "session" else f"/tasks/{task_id}/stream"
    assert prepare_v2(api, path, {}, object()) is None
    assert prepare_v2(api, path, {"cursor": "v2.signed"}, object()).status_code == 400
    events.append(
        SimpleNamespace(event=SimpleNamespace(event_type=EventType.SESSION_COMMAND_ACCEPTED))
    )
    assert prepare_v2(api, path, {}, object()).status_code == 409


def test_native_handoff_parent_canonical_history_has_no_child_drafts(owned, monkeypatch, tmp_path):
    import asyncio
    from datetime import timedelta
    from time import monotonic

    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.host_authority import HostResourceRef
    from agent_core.harness.models import HarnessEventDraft
    from agent_core.harness.orchestration_events import model_response_event
    from agent_storage.postgres.task_admission import load_session_task_binding, save_task_binding
    from zebra_agent_api.command_submission import submit_session_command
    from zebra_agent_api.routes import RouteRequest
    from zebra_agent_api.session_binding import renew_task_binding_snapshot
    from zebra_agent_api.session_streaming import tail_session_events
    from zebra_agent_api.stream_v2_reader import parse_record
    from zebra_agent_api.tenant_guard import tenant_scope_response
    from zebra_agent_worker.progress_recovery import recover_worker_progress
    from zebra_agent_worker.transient_output_composition import compose_transient_output_factory

    from tests.agent_core.test_stream_command_admission import capabilities
    from tests.agent_storage.test_postgres_agent_tasks import _append_handoff_events, _seed_session
    from tests.api.test_stream_v2_native import Request, opened
    from tests.stream_storage import native_environment
    from tests.worker.test_task_binding_host_context import _context, _verified

    bootstrap = native_environment.SessionBootstrapCommand
    monkeypatch.setattr(
        native_environment,
        "SessionBootstrapCommand",
        lambda **kw: bootstrap(host_context=_context(), **kw),
    )
    run, root_writer, response, reader, _, root_recovery = opened(owned, monkeypatch, frames=1)
    root_recovery.persist_with(run.recorder.append_draft)(
        model_response_event(response, attempt_number=1, response_stage="candidate")
    )
    child = _seed_session(owned[0], run.namespace, tmp_path / "child", "Child")
    _append_handoff_events(owned[0], run.namespace, root=run.session_id, child=child)
    task = run.stores.tasks.ensure_for_session(child)
    assert task.active_segment_id == child
    binding = load_session_task_binding(
        owned[0], deployment_namespace=run.namespace, session_id=child
    )
    original = binding.host_capability.host_context
    fresh = original.model_copy(
        update={
            "resource_refs": tuple(
                HostResourceRef(type="run", id="child-run") if ref.resource_type == "run" else ref
                for ref in original.resource_refs
            )
        }
    )
    renewed = renew_task_binding_snapshot(
        binding, fresh, authority_issuer=binding.host_capability.authority_issuer
    )
    save_task_binding(
        owned[0],
        deployment_namespace=run.namespace,
        binding=renewed,
        expected_previous_revision=binding.binding_revision,
    )
    events = run.stores.events.list_for_session(child)
    accepted = submit_session_command(
        run.stores,
        str(child),
        {
            "kind": "run",
            "expected_revision": events[-1].sequence,
            "payload": {
                "thread_id": str(run.task_id),
                "run_id": "child-run",
                "stream_capabilities": capabilities().model_dump(),
            },
        },
        idempotency_key="child-run",
        transient_admission_enabled=True,
        verified_host_grant=_verified(fresh),
    )
    assert accepted.status_code == 202
    events = run.stores.events.list_for_session(child)
    for kind, payload in (
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
        (EventType.MODEL_REQUEST_STARTED, {"attempt_number": 1, "model_call_id": "child-call"}),
    ):
        event = SessionEvent.create(
            session_id=child,
            sequence=events[-1].sequence + 1,
            event_type=kind,
            actor=EventActor.HARNESS,
            payload=payload,
        )
        run.stores.events.append(event)
        events.append(event)
    run.stores.sessions.save_session(rebuild_session(events))
    run.stores.tasks.ensure_for_session(child)
    lease = run.stores.leases.acquire(
        child, owner_instance_id="child-worker", ttl=timedelta(minutes=5)
    )
    recovery = recover_worker_progress(
        tasks=run.stores.tasks,
        namespace=run.namespace,
        session_id=child,
        ownership_check=lambda: None,
    )
    from zebra_agent_config import load_settings

    writer = compose_transient_output_factory(
        run.stores,
        dsn=owned[0],
        namespace=run.namespace,
        settings=load_settings({"ZEBRA_LIVE_REDIS_URL": owned[3]}),
    )(recovery, lease)
    writer.start_public_call("child-call", 1)
    writer.wrap(lambda _: pytest.fail("draft became durable"))(
        HarnessEventDraft(
            EventType.MODEL_RESPONSE_DELTA,
            EventActor.HARNESS,
            {"model_call_id": "child-call", "attempt_number": 1, "content_delta": "child draft"},
        )
    )
    assert not writer._failed
    run.stores.deployment_namespace = run.namespace
    api = SimpleNamespace(
        stream_v2_reader=reader,
        stores=run.stores,
        cloud_control=SimpleNamespace(
            deployment_namespace=run.namespace, load_task_binding=lambda _: renewed
        ),
    )
    parent_path = f"/sessions/{run.session_id}/stream"
    assert (
        tenant_scope_response(
            api,
            RouteRequest(
                "GET", parent_path, host_context=fresh, verified_host_grant=_verified(fresh)
            ),
        )
        is None
    )
    parent = prepare_v2(api, parent_path, {"recovery": "full"}, fresh)
    assert parent.session_id == str(run.session_id)
    child_context = prepare_v2(api, f"/sessions/{child}/stream", {}, fresh)
    assert child_context.session_id == str(child)
    calls = []
    original_discover = __import__(
        "zebra_agent_api.stream_v2_reader", fromlist=["discover"]
    ).discover
    monkeypatch.setattr(
        "zebra_agent_api.stream_v2_reader.discover",
        lambda *args: (calls.append(True), original_discover(*args))[1],
    )

    original_barrier = reader.notifications.barrier

    async def parent_barrier(key):
        assert not key.endswith(":authority:control")
        return await original_barrier(key)

    monkeypatch.setattr(reader.notifications, "barrier", parent_barrier)

    async def collect(context, session, *, draft=False):
        request = Request()
        source = tail_session_events(
            session_id=session,
            database_path=tmp_path / "unused",
            stores=run.stores,
            live_event_fanout=owned[2],
            deployment_namespace=run.namespace,
            authorization_expires_at=fresh.expires_at,
            request=request,
            after_sequence=int(context.cursor.durable or "0"),
            notifications=reader.notifications,
            recovery_notice=context.full_recovery,
        )
        stream = reader.tail(
            context, source, deadline=monotonic() + 2, disconnected=request.is_disconnected
        )
        result = []
        try:
            async for wire in stream:
                token, event = parse_record(wire)
                result.append((token, event))
                if draft and event.get("name") == "zebra.stream.draft":
                    break
                if not draft and event.get("name") == "zebra.stream.recovery_complete":
                    break
        finally:
            await stream.aclose()
        return result

    try:
        history = asyncio.run(collect(parent, run.session_id))
        assert not calls
        assert any(
            event.get("event_type") == "model_response_received"
            and event["payload"]["assistant_message"] == "Canonical full response"
            for _, event in history
        )
        assert not any(event.get("name") == "zebra.stream.draft" for _, event in history)
        token = next(token for token, _ in reversed(history) if token)
        with pytest.raises(ValueError):
            reader.context(
                child_context.binding,
                kind="session",
                token=token,
                full_recovery=False,
                session_id=str(child),
            )
        resumed = prepare_v2(api, parent_path, {"cursor": token}, fresh)
        frontier = int(resumed.cursor.durable)
        assert frontier == run.stores.events.list_for_session(run.session_id)[-1].sequence
        continued = asyncio.run(collect(resumed, run.session_id))
        assert all(event.get("sequence", frontier + 1) > frontier for _, event in continued)
        assert not any(event.get("name") == "zebra.stream.draft" for _, event in continued)
        cold = prepare_v2(api, parent_path, {"recovery": "full", "cursor": token}, fresh)
        assert cold.cursor.durable is None
        assert asyncio.run(collect(cold, run.session_id))
        assert not calls
        monkeypatch.setattr(reader.notifications, "barrier", original_barrier)
        live = asyncio.run(collect(child_context, child, draft=True))
        assert any(
            event.get("name") == "zebra.stream.draft"
            and event["value"]["content_delta"] == "child draft"
            for _, event in live
        )
    finally:
        writer.close()
        root_writer.close()
        asyncio.run(reader.close())
