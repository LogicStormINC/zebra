"""Actual cloud callback sources + native PG/Redis + all three API stream bodies."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic

import pytest
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelTextDelta
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.orchestration_events import model_response_event
from zebra_agent_api.ag_ui_stream import prepare_agui_stream, tail_agui_events
from zebra_agent_api.session_streaming import tail_session_events, tail_task_events
from zebra_agent_api.stream_v2_authority import V2ReadAuthority
from zebra_agent_api.stream_v2_reader import StreamV2Reader, parse_record
from zebra_agent_worker.transient_output_composition import compose_transient_output_factory

from tests.worker.test_transient_output_composition_native import owned as _owned_fixture
from tests.worker.test_transient_output_composition_native import setup

owned = _owned_fixture


def materialize(stores, task_id, owned):
    from agent_core.ports.task_projection_checkpoints import ProjectionScope
    from agent_integrations.ag_ui.checkpoint_consumer import AgUiCheckpointConsumer

    queue = stores.projection_work
    consumer = AgUiCheckpointConsumer(
        stores.tasks,
        queue,
        namespace=stores.namespace,
        checkpoint_committed=owned[2].publish_checkpoint,
    )
    for _ in range(100):
        consumer.poll_once(budget_seconds=1)
        run = stores.tasks.read_run_header(task_id, "run-v2")
        assert run.anchor is not None
        scope = ProjectionScope(stores.namespace, task_id, run.anchor.event_id, "ag-ui-v1")
        if stores.tasks.read_checkpoint_head(scope).through_sequence >= run.highwater:
            return
    pytest.fail("actual checkpoint consumer did not catch up")


class Request:
    async def is_disconnected(self):
        return False


def opened(owned, monkeypatch, *, frames=100, content=" 普通草稿🙂 "):
    run, lease, recovery, binding, settings = setup(owned, monkeypatch)
    writer = compose_transient_output_factory(
        run.stores, dsn=owned[0], namespace=run.namespace, settings=settings
    )(recovery, lease)
    assert writer is not None
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.projection_work import PostgresTaskProjectionWorkStore

    queue = PostgresTaskProjectionWorkStore(
        PostgresDatabase(owned[0], deployment_namespace=run.namespace), "ag-ui-v1"
    )
    queue.enable_projection_work()
    run.stores.projection_work = queue

    class Provider:
        def complete_stream(self, _messages, *, tools=(), on_text_delta):
            for index in range(frames):
                on_text_delta(ModelTextDelta(index=index, content=content))
            return ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Canonical full response",
                    created_at=datetime.now(UTC),
                )
            )

    response = HarnessModelStep(
        event_sink=writer.wrap(recovery.persist_with(run.recorder.append_draft)),
        public_call_started=writer.start_public_call,
    ).request_completion([], Provider(), allow_tools=True)
    assert not writer._failed and writer._offset == frames
    assert writer._gate is not None
    authority = V2ReadAuthority(
        run.stores,
        dsn=owned[0],
        namespace=run.namespace,
        key_prefix=f"{owned[2]._key_prefix}:admission",
    )
    reader = StreamV2Reader(
        authority,
        url=owned[3],
        key=b"native-shared-cursor-fixture-key-32",
        live_prefix=owned[2]._key_prefix,
    )
    bound = authority.bind(run.task_id, "run-v2", binding.host_capability.host_context)
    assert bound is not None
    return run, writer, response, reader, bound, recovery


@pytest.mark.parametrize("route", ["session", "task", "agui"])
def test_native_three_actual_reader_paths_recover_full_prefix_with_signed_cursors(
    owned,
    monkeypatch,
    tmp_path,
    route,
):
    run, writer, _, reader, bound, _ = opened(owned, monkeypatch)
    request = Request()
    context = reader.context(bound, kind=route, token=None, full_recovery=True)
    materialize(run.stores, run.task_id, owned)
    calls = []
    original = reader.authority.qualify

    def qualify(*args):
        calls.append(monotonic())
        return original(*args)

    monkeypatch.setattr(reader.authority, "qualify", qualify)

    async def collect():
        if route == "agui":
            prepared = prepare_agui_stream(
                run.stores,
                f"/agui/threads/{run.task_id}/runs/run-v2/stream",
                {},
                live_event_fanout=owned[2],
                deployment_namespace=run.namespace,
                authorization_expires_at=bound.host.expires_at,
                host_context=bound.host,
                notifications=reader.notifications,
                recovery_notice=True,
            )
            assert not hasattr(prepared, "status_code")
            source = tail_agui_events(prepared, request)
        else:
            options = dict(
                database_path=tmp_path / "unused",
                stores=run.stores,
                live_event_fanout=owned[2],
                deployment_namespace=run.namespace,
                authorization_expires_at=bound.host.expires_at,
                request=request,
                after_sequence=0,
                notifications=reader.notifications,
                recovery_notice=True,
            )
            source = (
                tail_task_events(task_id=run.task_id, **options)
                if route == "task"
                else tail_session_events(session_id=run.session_id, **options)
            )
        frames = []
        try:
            async for wire in reader.tail(
                context, source, deadline=monotonic() + 3, disconnected=request.is_disconnected
            ):
                frames.append(wire)
                if sum('"zebra.stream.draft"' in frame for frame in frames) >= 100:
                    break
            return frames
        finally:
            await reader.close()

    try:
        frames = asyncio.run(collect())
        drafts = [parse_record(frame)[1] for frame in frames if '"zebra.stream.draft"' in frame]
        assert len(drafts) == 100
        assert [event["value"]["offset"] for event in drafts] == list(range(100))
        assert all(
            event["value"]["chunk_index"] == 0 and event["value"]["last"] for event in drafts
        )
        assert len(calls) <= 2
        assert all(len(frame.encode()) <= 16384 for frame in frames)
        for frame in frames:
            token, event = parse_record(frame)
            if token:
                decoded = reader.codec.decode(token, scope=context.cursor.scope)
                if event.get("name") == "zebra.stream.draft":
                    assert decoded.live_offset == event["value"]["offset"]
        assert any('"zebra.stream.recovery_complete"' in frame for frame in frames)
    finally:
        writer.close()


def test_native_canonical_response_blocks_stale_redis_descriptor_without_close_ack(
    owned,
    monkeypatch,
):
    run, writer, response, reader, bound, recovery = opened(owned, monkeypatch, frames=10)
    descriptor = reader.port._client.hget(bound.lane + ":authority", "descriptor")
    assert descriptor is not None
    from agent_integrations.redis_transient_discovery import TransientDescriptor

    decoded = TransientDescriptor.model_validate_json(descriptor)
    assert reader.authority.qualify(bound, decoded) > datetime.now(UTC)
    # Keep the visual authority/hash open to simulate a lost close/control operation.
    recovery.persist_with(run.recorder.append_draft)(
        model_response_event(response, attempt_number=1, response_stage="candidate")
    )
    with pytest.raises(ValueError, match="canonical response"):
        reader.authority.qualify(bound, decoded)
    asyncio.run(reader.close())
    writer.close()


@pytest.mark.parametrize("route", ["session", "task", "agui"])
def test_native_signed_http_routes_negotiate_v2_and_reject_tampering(
    owned,
    monkeypatch,
    tmp_path,
    route,
):
    from uuid import uuid4

    import jwt
    from agent_core.domain.cloud_scope import OpaqueAuthorityScope
    from agent_security import PyJwtHostGrantDecoder
    from agent_storage import (
        HostRegistryRecord,
        PostgresHostAuthorityStore,
        postgres_control_plane_stores,
    )
    from cryptography.hazmat.primitives.asymmetric import rsa
    from fastapi.testclient import TestClient
    from zebra_agent_api import create_http_app, http
    from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer
    from zebra_agent_config.settings import LiveEventSettings
    from zebra_agent_config.stream_settings import StreamSettings

    from tests.api.test_host_auth_http import _cloud_settings
    from tests.api.test_postgres_host_auth_authorizer import _StaticResolver
    from tests.stream_storage import native_environment
    from tests.test_cloud_api_worker_profile_composition import _ObjectReader
    from tests.worker.test_task_binding_host_context import _context

    bootstrap = native_environment.SessionBootstrapCommand
    monkeypatch.setattr(
        native_environment,
        "SessionBootstrapCommand",
        lambda **kw: bootstrap(host_context=_context(), **kw),
    )
    run, writer, _, reader, bound, _ = opened(owned, monkeypatch, frames=10)
    materialize(run.stores, run.task_id, owned)
    history = OpaqueAuthorityScope(
        authority_issuer=bound.authority.authority_issuer,
        namespace_id=bound.authority.namespace_id,
        allowed_session_ids=(str(run.session_id),),
    )
    stores = postgres_control_plane_stores(
        owned[0],
        deployment_namespace=run.namespace,
        memory_cursor_signing_key=b"native-memory-cursor-fixture-key-32",
        artifact_objects=_ObjectReader(),
        history_scope=history,
        continuation_scope=history,
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    registry = PostgresHostAuthorityStore(owned[0], deployment_namespace=run.namespace)
    registry.upsert_registry(
        HostRegistryRecord(
            host_app_id=bound.host.host_app_id,
            namespace_id=bound.host.namespace_id,
            issuer=bound.authority.authority_issuer,
            audience="native-stream",
            jwks_uri=bound.host.origin + "/.well-known/jwks.json",
            allowed_origins=(bound.host.origin,),
            algorithms=("RS256",),
            policy_version=bound.host.policy_version,
        )
    )
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry=registry,
        decoder=PyJwtHostGrantDecoder(_StaticResolver(key.public_key())),
    )
    settings = replace(
        _cloud_settings(owned[0]),
        live_events=LiveEventSettings(redis_url=owned[3], key_prefix=owned[2]._key_prefix),
        stream=StreamSettings(cursor_signing_key=b"native-shared-cursor-fixture-key-32"),
    )
    original = http.create_app
    apis = []

    def capture(*args, **kwargs):
        api = original(*args, **kwargs)
        api.stream_v2_reader.authority = reader.authority
        apis.append(api)
        return api

    monkeypatch.setattr(http, "create_app", capture)
    monkeypatch.setattr("zebra_agent_api.session_streaming._MAX_STREAM_SECONDS", 1.5)
    app = create_http_app(
        tmp_path / "http-unused", settings=settings, stores=stores, host_grant_authorizer=authorizer
    )
    path = (
        f"/agui/threads/{run.task_id}/runs/run-v2/stream"
        if route == "agui"
        else f"/tasks/{run.task_id}/stream"
        if route == "task"
        else f"/sessions/{run.session_id}/stream"
    )

    def headers():
        now = int(datetime.now(UTC).timestamp())
        claims = {
            **bound.host.model_dump(mode="json", exclude={"grant_id", "expires_at"}),
            "scopes": ["agent.run", "event.read", "trench:source:read"],
            "iss": bound.authority.authority_issuer,
            "aud": "native-stream",
            "sub": "user-1",
            "jti": uuid4().hex,
            "iat": now - 1,
            "nbf": now - 1,
            "exp": now + 60,
        }
        return {
            "Authorization": "Bearer " + jwt.encode(claims, key, algorithm="RS256"),
            "Origin": bound.host.origin,
        }

    try:
        with TestClient(app) as client:
            response = client.get(path, params={"recovery": "full"}, headers=headers())
            assert response.status_code == 200, (
                response.json() if response.status_code != 200 else "stream"
            )
            frames = response.text.strip().split("\n\n")
            drafts = [parse_record(frame)[1] for frame in frames if '"zebra.stream.draft"' in frame]
            assert len(drafts) == 10
            token = next(
                parse_record(frame)[0] for frame in reversed(frames) if parse_record(frame)[0]
            )
            assert token.startswith("v2.")
            denied = client.get(path, params={"cursor": token[:-1] + "!"}, headers=headers())
            assert denied.status_code == 400
            configured_reader = apis[0].stream_v2_reader
            object.__setattr__(apis[0], "stream_v2_reader", None)
            try:
                unavailable = client.get(path, params={"recovery": "full"}, headers=headers())
                assert unavailable.status_code == 503
                assert unavailable.json()["code"] == "stream_v2_unavailable"
            finally:
                object.__setattr__(apis[0], "stream_v2_reader", configured_reader)
    finally:
        writer.close()
        asyncio.run(reader.close())


@pytest.mark.parametrize(
    "mutation", ["namespace", "owner", "turn", "expired", "run", "public_expression", "coverage"]
)
def test_native_locator_never_authorizes_changed_source_or_scope(owned, monkeypatch, mutation):
    from datetime import timedelta
    from uuid import uuid4

    from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
    from agent_core.harness.models import HarnessEventDraft
    from agent_integrations.redis_transient_discovery import discover

    run, writer, _, reader, bound, recovery = opened(owned, monkeypatch, frames=1)
    descriptor, _ = discover(reader.port._client, bound.lane)
    assert reader.authority.qualify(bound, descriptor) > datetime.now(UTC)
    if mutation == "namespace":
        descriptor = descriptor.model_copy(
            update={
                "scope": descriptor.scope.model_copy(
                    update={
                        "authority_scope": descriptor.scope.authority_scope.model_copy(
                            update={"namespace_id": "foreign"}
                        ),
                    }
                )
            }
        )
    elif mutation == "owner":
        descriptor = descriptor.model_copy(
            update={"fence": descriptor.fence.model_copy(update={"owner_instance_id": "foreign"})}
        )
    elif mutation == "turn":
        descriptor = descriptor.model_copy(
            update={
                "scope": descriptor.scope.model_copy(
                    update={
                        "generation": descriptor.scope.generation.model_copy(
                            update={"turn_id": uuid4()}
                        ),
                    }
                )
            }
        )
    elif mutation == "expired":
        bound = replace(
            bound,
            host=bound.host.model_copy(
                update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            ),
        )
    elif mutation == "run":
        command = SessionCommand(
            session_id=run.session_id,
            kind=SessionCommandKind.RUN,
            expected_revision=run.recorder.session.current_sequence,
            idempotency_key=uuid4().hex,
            payload={"run_id": "new-run"},
        )
        run.recorder.append(
            EventType.SESSION_COMMAND_ACCEPTED, EventActor.USER, command.event_payload()
        )
    elif mutation == "public_expression":
        recovery.persist_with(run.recorder.append_draft)(
            HarnessEventDraft(
                EventType.MODEL_REQUEST_STARTED,
                EventActor.HARNESS,
                {
                    "model_call_id": "expression",
                    "attempt_number": 1,
                    "purpose": "public_expression",
                },
            )
        )
        identity = descriptor.scope.generation.model_copy(
            update={"model_call_id": "expression", "message_id": "message:expression"}
        )
        descriptor = descriptor.model_copy(
            update={
                "scope": descriptor.scope.model_copy(update={"generation": identity}),
                "request_sequence": recovery.head.through_sequence,
            }
        )
    else:
        # The existing privacy contract treats even malformed historical presence as private.
        from agent_core.domain.events import SessionEvent

        event = SessionEvent.create(
            session_id=run.session_id,
            sequence=run.recorder.session.current_sequence + 1,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.HARNESS,
            payload={"title": "marker"},
        )
        run.stores.events.append(
            event.model_copy(
                update={
                    "event_type": EventType.TASK_PREPARED,
                    "payload": {"coverage_admission": None},
                }
            )
        )
    try:
        with pytest.raises(ValueError):
            reader.authority.qualify(bound, descriptor)
    finally:
        writer.close()
        asyncio.run(reader.close())


@pytest.mark.parametrize("reset_before_resume", [False, True])
def test_native_exact_partial_live_resume_and_endpoint_cursor_scope(
    owned, monkeypatch, tmp_path, reset_before_resume
):
    run, writer, _, reader, bound, _ = opened(owned, monkeypatch, frames=2, content="🙂" * 2000)
    request = Request()

    async def collect():
        first = reader.context(bound, kind="task", token=None, full_recovery=True)
        options = dict(
            database_path=tmp_path / "unused",
            stores=run.stores,
            task_id=run.task_id,
            request=request,
            live_event_fanout=owned[2],
            deployment_namespace=run.namespace,
            authorization_expires_at=bound.host.expires_at,
            notifications=reader.notifications,
        )
        source = tail_task_events(after_sequence=0, recovery_notice=True, **options)
        stream = reader.tail(
            first, source, deadline=monotonic() + 3, disconnected=request.is_disconnected
        )
        prefix = []
        async for wire in stream:
            token, event = parse_record(wire)
            if event.get("name") == "zebra.stream.draft":
                prefix.append(event["value"]["content_delta"])
                assert event["value"]["last"] is False
                break
        await stream.aclose()
        decoded = reader.codec.decode(token, scope=first.cursor.scope)
        assert decoded.live_chunk_index == 0 and decoded.live_offset is None
        with pytest.raises(ValueError):
            reader.context(bound, kind="session", token=token, full_recovery=False)
        resumed = reader.context(bound, kind="task", token=token, full_recovery=False)
        if reset_before_resume:
            original_barrier = reader.notifications.barrier

            async def barrier(key):
                if key.endswith(":control"):
                    raise ConnectionError("owned startup notification failure")
                return await original_barrier(key)

            monkeypatch.setattr(reader.notifications, "barrier", barrier)

        source = tail_task_events(after_sequence=int(decoded.durable or "0"), **options)
        stream = reader.tail(
            resumed, source, deadline=monotonic() + 3, disconnected=request.is_disconnected
        )
        suffix = []
        try:
            async for wire in stream:
                _, event = parse_record(wire)
                if event.get("name") == "zebra.stream.draft":
                    suffix.append(event)
                    if event["value"]["offset"] == 1 and event["value"]["last"]:
                        break
            assert suffix[0]["value"]["chunk_index"] == (0 if reset_before_resume else 1)
            assert (
                "".join(
                    ([] if reset_before_resume else prefix)
                    + [event["value"]["content_delta"] for event in suffix]
                )
                == "🙂" * 4000
            )
        finally:
            await stream.aclose()
            await reader.close()

    try:
        asyncio.run(collect())
    finally:
        writer.close()


def test_native_expired_request_grant_emits_no_canonical_or_provisional_frames(owned, monkeypatch):
    from datetime import timedelta

    run, writer, response, reader, bound, recovery = opened(owned, monkeypatch, frames=1)
    recovery.persist_with(run.recorder.append_draft)(
        model_response_event(response, attempt_number=1, response_stage="candidate")
    )
    expired = replace(
        bound,
        host=bound.host.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}),
    )
    context = reader.context(expired, kind="task", token=None, full_recovery=True)

    async def source():
        pytest.fail("expired authority advanced the canonical reader")
        yield "data: {}\n\n"

    async def collect():
        try:
            return [
                frame
                async for frame in reader.tail(
                    context,
                    source(),
                    deadline=monotonic() + 2,
                    disconnected=Request().is_disconnected,
                )
            ]
        finally:
            await reader.close()

    try:
        assert asyncio.run(collect()) == []
    finally:
        writer.close()


@pytest.mark.parametrize("route", ["session", "task", "agui"])
def test_native_blackhole_startup_budget_preserves_durable_recovery(
    owned, monkeypatch, tmp_path, route
):
    import socket
    import threading

    run, writer, response, reader, bound, recovery = opened(owned, monkeypatch, frames=1)
    recovery.persist_with(run.recorder.append_draft)(
        model_response_event(response, attempt_number=1, response_stage="candidate")
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)
    stopped = threading.Event()
    sockets = []

    def accept():
        while not stopped.is_set():
            try:
                sockets.append(listener.accept()[0])  # Own socket accepts but never replies.
            except TimeoutError:
                pass

    thread = threading.Thread(target=accept)
    thread.start()
    original = reader
    reader = StreamV2Reader(
        original.authority,
        url=f"redis://127.0.0.1:{listener.getsockname()[1]}",
        key=b"native-shared-cursor-fixture-key-32",
        live_prefix=owned[2]._key_prefix,
    )

    async def collect():
        request = Request()
        if route == "agui":
            materialize(run.stores, run.task_id, owned)
            prepared = prepare_agui_stream(
                run.stores,
                f"/agui/threads/{run.task_id}/runs/run-v2/stream",
                {},
                live_event_fanout=owned[2],
                deployment_namespace=run.namespace,
                authorization_expires_at=bound.host.expires_at,
                host_context=bound.host,
                notifications=reader.notifications,
                recovery_notice=True,
            )
            assert not hasattr(prepared, "status_code")
            source = tail_agui_events(prepared, request)
        else:
            options = dict(
                database_path=tmp_path / "unused",
                stores=run.stores,
                live_event_fanout=owned[2],
                deployment_namespace=run.namespace,
                authorization_expires_at=bound.host.expires_at,
                request=request,
                after_sequence=0,
                notifications=reader.notifications,
                recovery_notice=True,
            )
            source = (
                tail_task_events(task_id=run.task_id, **options)
                if route == "task"
                else tail_session_events(session_id=run.session_id, **options)
            )
        context = reader.context(bound, kind=route, token=None, full_recovery=True)
        started = monotonic()
        result = []
        async for frame in reader.tail(
            context, source, deadline=started + 1.5, disconnected=request.is_disconnected
        ):
            result.append(parse_record(frame)[1])
            if (
                result[-1].get("event_type") == "model_response_received"
                or result[-1].get("name") == "zebra.message_replace"
            ):
                return monotonic() - started, result
        pytest.fail(
            "blackhole consumed durable deadline: "
            + str([(e.get("type"), e.get("name")) for e in result])
        )

    try:
        elapsed, events = asyncio.run(collect())
        assert elapsed < 1
        assert any(event.get("name") == "zebra.stream.reset" for event in events)
        assert not any(event.get("name") == "zebra.stream.draft" for event in events)
        final = events[-1]
        if route == "agui":
            assert final["value"]["content"] == "Canonical full response"
        else:
            assert final["payload"]["assistant_message"] == "Canonical full response"

    finally:
        stopped.set()
        thread.join(timeout=1)
        listener.close()
        for connection in sockets:
            connection.close()
        writer.close()
        asyncio.run(reader.close())
        asyncio.run(original.close())
