"""Native accepted metadata, source Turn, persisted Host binding and real model hook."""

import os
from datetime import UTC, datetime, timedelta
from time import monotonic

import pytest
from agent_core.application.turn_projection import current_turn
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.identifiers import new_event_id, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCallMetadata, ModelCompletion, ModelTextDelta
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.orchestration_events import model_response_event
from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy
from agent_integrations.redis_transient_output import RedisTransientOutput
from agent_integrations.run_stream_admission import load_run_stream_admission
from agent_storage import PostgresLeaseStore
from agent_storage.postgres.task_admission import save_task_binding
from zebra_agent_api.command_submission import submit_session_command
from zebra_agent_api.session_binding import _build_binding_snapshot
from zebra_agent_config import load_settings
from zebra_agent_worker.progress_recovery import recover_worker_progress
from zebra_agent_worker.transient_output_composition import compose_transient_output_factory

from tests.agent_core.test_stream_command_admission import capabilities
from tests.stream_storage.native_environment import native_environment, seed
from tests.stream_storage.telemetry import Telemetry, phase
from tests.worker.test_task_binding_host_context import _context, _verified


@pytest.fixture(scope="module")
def owned():
    dsn, url = (
        os.environ.get("ZEBRA_STREAM_TEST_POSTGRES_DSN"),
        os.environ.get("ZEBRA_STREAM_TEST_REDIS_URL"),
    )
    if not dsn or not url:
        pytest.skip("set owned native PostgreSQL/Redis endpoints")
    with native_environment(dsn, url) as (scratch, client, fanout):

        class OwnedEndpoints(tuple):
            def __repr__(self):
                return "Owned disposable PostgreSQL/Redis endpoints"

        yield OwnedEndpoints((scratch, client, fanout, url))


def setup(owned, monkeypatch, *, oversized_history=False):
    dsn, _, fanout, url = owned
    run = seed(dsn, fanout, 1)
    leases = PostgresLeaseStore(dsn, deployment_namespace=run.namespace)
    run.stores.leases = leases
    lease = leases.get(run.session_id)
    assert lease is not None
    if oversized_history:
        run.recorder.append(
            EventType.MODEL_REQUEST_STARTED,
            EventActor.HARNESS,
            {"model_call_id": "old-call", "attempt_number": 1},
        )
        old = ModelCompletion(
            call_metadata=ModelCallMetadata(model_call_id="old-call"),
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content="x" * 1_100_000,
                created_at=datetime.now(UTC),
            ),
        )
        run.recorder.append_draft(
            model_response_event(old, attempt_number=1, response_stage="candidate")
        )
    context = _context()
    context = context.model_copy(
        update={
            "resource_refs": tuple(
                HostResourceRef(type="run", id="run-v2") if ref.resource_type == "run" else ref
                for ref in context.resource_refs
            )
        }
    )
    payload = {
        "kind": "run",
        "expected_revision": run.recorder.session.current_sequence,
        "payload": {
            "thread_id": str(run.task_id),
            "run_id": "run-v2",
            "stream_capabilities": capabilities().model_dump(),
        },
    }
    accepted = submit_session_command(
        run.stores,
        str(run.session_id),
        payload,
        idempotency_key="accepted-v2",
        transient_admission_enabled=True,
        verified_host_grant=_verified(context),
    )
    assert (
        accepted.status_code == 202 and accepted.body["stream_admission"]["mode"] == "transient_v2"
    )
    duplicate = submit_session_command(
        run.stores,
        str(run.session_id),
        payload,
        idempotency_key="accepted-v2",
        transient_admission_enabled=False,
    )
    assert (
        duplicate.status_code == 200
        and duplicate.body["stream_admission"] == accepted.body["stream_admission"]
    )
    assert (
        load_run_stream_admission(run.stores.tasks, run.task_id, "run-v2").mode.value
        == "transient_v2"
    )
    run.recorder.append(
        EventType.HARNESS_ATTEMPT_STARTED, EventActor.HARNESS, {"attempt_number": 1}
    )
    binding = _build_binding_snapshot(
        str(run.task_id),
        host_context=context,
        verified_host_grant=_verified(context),
        definition_snapshot_digest="a" * 64,
    )
    save_task_binding(dsn, deployment_namespace=run.namespace, binding=binding)
    progress = recover_worker_progress(
        tasks=run.stores.tasks,
        namespace=run.namespace,
        session_id=run.session_id,
        ownership_check=lambda: None,
    )
    settings = load_settings({"ZEBRA_LIVE_REDIS_URL": url})
    original = RedisTransientOutput.from_url
    monkeypatch.setattr(
        RedisTransientOutput,
        "from_url",
        lambda address, **kw: original(
            address, **{**kw, "key_prefix": f"{fanout._key_prefix}:admission"}
        ),
    )
    return run, lease, progress, binding, settings


def test_native_mode_aware_model_hook_exact_turn_timer_and_zero_frame_sql(
    owned, monkeypatch, record_property
):
    run, lease, recovery, _, settings = setup(owned, monkeypatch, oversized_history=True)
    factory = compose_transient_output_factory(
        run.stores, dsn=owned[0], namespace=run.namespace, settings=settings
    )
    writer = factory(recovery, lease)
    assert writer is not None and writer._port is not None
    from zebra_agent_worker import transient_output_composition as composition

    def immutable_read_forbidden(*args, **kwargs):
        raise AssertionError("proven immutable admission must not be reread")

    monkeypatch.setattr(composition, "load_run_stream_admission", immutable_read_forbidden)
    progress = ProgressiveEventSink(
        writer.wrap(recovery.persist_with(run.recorder.append_draft)),
        user_input="x",
        policy=PublicOutputPolicy(expression_max_calls=0),
        recovery_state=recovery.head.state,
        output_published=recovery.output_published,
        receipts_covered=recovery.receipts_covered,
    )
    scopes = []
    activation_times = []

    def hook(call, attempt):
        # A canonical timer fact lands after request commit and before the hook.
        recovery.persist_with(run.recorder.append_draft)(
            HarnessEventDraft(
                EventType.PUBLIC_OUTPUT,
                EventActor.HARNESS,
                {
                    "attempt_number": 1,
                    "output_id": f"wait:{call}",
                    "kind": "status",
                    "phase": "waiting",
                    "origin": "system",
                    "content": "Working",
                },
            )
        )
        started = monotonic()
        with phase("native/real-composition-activation"):
            writer.start_public_call(call, attempt)
        activation_times.append(monotonic() - started)
        assert not writer._failed
        assert writer._gate.request_sequence < recovery.head.through_sequence
        scopes.append(writer._gate.scope)

    class Provider:
        count = 10

        def complete_stream(self, _messages, *, tools=(), on_text_delta):
            with phase("native/real-composition-text"):
                for index in range(self.count):
                    on_text_delta(ModelTextDelta(index=index, content=" ordinary draft "))
            return ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Full candidate response",
                    created_at=datetime.now(UTC),
                )
            )

    provider = Provider()
    telemetry = Telemetry()
    step = HarnessModelStep(event_sink=progress, public_call_started=hook)
    try:
        with telemetry.installed():
            for count in (10, 100):
                provider.count = count
                response = step.request_completion([], provider, allow_tools=True)
                assert writer._offset == count and progress._model_spoke
                expected = current_turn(run.stores.events.list_for_session(run.session_id)).turn_id
                assert str(scopes[-1].generation.turn_id) == expected
                assert scopes[-1].authority_scope.allowed_session_ids == (str(run.session_id),)
                progress(
                    model_response_event(response, attempt_number=1, response_stage="candidate")
                )
        assert (
            sum(
                value
                for key, value in telemetry.calls.items()
                if "/native/real-composition-text/sql:" in key
            )
            == 0
        )
        record_property(
            "activation_sql_two_calls",
            sum(
                value
                for key, value in telemetry.calls.items()
                if "/native/real-composition-activation/sql:" in key
            ),
        )
        record_property(
            "provider_frame_sql_two_calls",
            sum(
                value
                for key, value in telemetry.calls.items()
                if "/native/real-composition-text/sql:" in key
            ),
        )
        record_property(
            "activation_seconds", ",".join(f"{value:.4f}" for value in activation_times)
        )
        record_property(
            "measured_total_sql_two_requests_responses",
            sum(value for key, value in telemetry.calls.items() if "/sql:" in key),
        )
        events = run.stores.events.list_for_session(run.session_id)
        assert not any(event.event_type is EventType.MODEL_RESPONSE_DELTA for event in events)
        assert sum(event.event_type is EventType.MODEL_RESPONSE_RECEIVED for event in events) == 3
    finally:
        progress.close()
        writer.close()
        writer._port._client.close()


@pytest.mark.parametrize(
    "fault", ["expiry", "run_target", "closed_turn", "missing_redis", "source_fault", "stale_lease"]
)
def test_native_faults_suppress_draft_but_keep_full_response(owned, monkeypatch, fault):
    run, lease, recovery, binding, settings = setup(owned, monkeypatch)
    if fault in {"expiry", "run_target"}:
        host = binding.host_capability
        context = host.host_context
        if fault == "expiry":
            context = context.model_copy(
                update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            )
        else:
            context = context.model_copy(
                update={
                    "resource_refs": tuple(
                        HostResourceRef(type="run", id="wrong")
                        if ref.resource_type == "run"
                        else ref
                        for ref in context.resource_refs
                    )
                }
            )
        changed = binding.model_copy(
            update={
                "binding_revision": 2,
                "host_capability": host.model_copy(update={"host_context": context}),
            }
        )
        save_task_binding(owned[0], deployment_namespace=run.namespace, binding=changed)
    if fault == "missing_redis":
        from dataclasses import replace

        settings = replace(settings, live_events=replace(settings.live_events, redis_url=None))
    if fault == "source_fault":
        monkeypatch.setattr(
            run.stores.tasks,
            "read_run_header",
            lambda *args, **kw: (_ for _ in ()).throw(TimeoutError()),
        )
    writer = compose_transient_output_factory(
        run.stores, dsn=owned[0], namespace=run.namespace, settings=settings
    )(recovery, lease)
    assert writer is not None
    if fault == "source_fault":
        monkeypatch.undo()
    call = "fault-call"
    recovery.persist_with(run.recorder.append_draft)(
        HarnessEventDraft(
            EventType.MODEL_REQUEST_STARTED,
            EventActor.HARNESS,
            {"model_call_id": call, "attempt_number": 1},
        )
    )
    if fault == "closed_turn":
        turn = current_turn(run.stores.events.list_for_session(run.session_id))
        run.recorder.append(
            EventType.TURN_COMPLETED,
            EventActor.HARNESS,
            {
                "turn_id": turn.turn_id,
                "turn_index": turn.turn_index,
                "summary": "closed",
                "closes_segment": False,
            },
        )
        recovery.catch_up()
    if fault == "stale_lease":
        run.stores.leases.release(run.session_id, fence=lease.fence)
    writer.start_public_call(call, 1)
    assert writer._failed
    saved = []
    output = writer.wrap(saved.append)
    output(
        HarnessEventDraft(
            EventType.MODEL_RESPONSE_DELTA,
            EventActor.HARNESS,
            {"model_call_id": call, "attempt_number": 1, "content_delta": "draft"},
        )
    )
    output(
        HarnessEventDraft(
            EventType.MODEL_RESPONSE_RECEIVED,
            EventActor.HARNESS,
            {"model_call_id": call, "attempt_number": 1, "content": "Full response"},
        )
    )
    assert [event.event_type for event in saved] == [EventType.MODEL_RESPONSE_RECEIVED]
    writer.close()
    if writer._port is not None:
        writer._port._client.close()


def test_native_handoff_uses_root_host_binding_and_active_child_turn(owned, monkeypatch, tmp_path):
    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.events import SessionEvent
    from agent_core.domain.identifiers import SessionId
    from zebra_agent_api.session_binding import renew_task_binding_snapshot

    from tests.agent_storage.test_postgres_agent_tasks import _append_handoff_events, _seed_session

    run, _, _, binding, settings = setup(owned, monkeypatch)
    child = _seed_session(owned[0], run.namespace, tmp_path / "child", "Child")
    _append_handoff_events(owned[0], run.namespace, root=run.session_id, child=child)
    task = run.stores.tasks.ensure_for_session(child)
    assert task.task_id == run.task_id and task.active_segment_id == child
    context = binding.host_capability.host_context
    fresh = context.model_copy(
        update={
            "resource_refs": tuple(
                HostResourceRef(type="run", id="child-run") if ref.resource_type == "run" else ref
                for ref in context.resource_refs
            )
        }
    )
    renewed = renew_task_binding_snapshot(
        binding, fresh, authority_issuer=binding.host_capability.authority_issuer
    )
    save_task_binding(
        owned[0], deployment_namespace=run.namespace, binding=renewed, expected_previous_revision=1
    )
    events = run.stores.events.list_for_session(child)
    response = submit_session_command(
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
    assert response.status_code == 202
    events = run.stores.events.list_for_session(child)
    for kind, payload in (
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
        (EventType.MODEL_REQUEST_STARTED, {"attempt_number": 1, "model_call_id": "child-call"}),
    ):
        event = SessionEvent.create(
            session_id=SessionId(child),
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
    writer = compose_transient_output_factory(
        run.stores, dsn=owned[0], namespace=run.namespace, settings=settings
    )(recovery, lease)
    try:
        writer.start_public_call("child-call", 1)
        assert not writer._failed
        scope = writer._gate.scope
        assert scope.generation.task_id == run.task_id
        assert scope.generation.segment_id == child
        assert str(scope.generation.turn_id) == current_turn(events).turn_id
        assert scope.authority_scope.allowed_session_ids == (str(child),)
        assert scope.authority_scope.namespace_id == binding.host_capability.namespace_id
    finally:
        writer.close()
        if writer._port is not None:
            writer._port._client.close()


def test_native_cached_mode_still_rejects_changed_current_run_anchor(owned, monkeypatch):
    from dataclasses import replace
    from uuid import uuid4

    from agent_integrations.redis_transient_output import TransientOutputUnavailable

    run, lease, recovery, _, settings = setup(owned, monkeypatch)
    writer = compose_transient_output_factory(
        run.stores, dsn=owned[0], namespace=run.namespace, settings=settings
    )(recovery, lease)
    recovery.persist_with(run.recorder.append_draft)(
        HarnessEventDraft(
            EventType.MODEL_REQUEST_STARTED,
            EventActor.HARNESS,
            {"model_call_id": "anchor-check", "attempt_number": 1},
        )
    )
    writer.start_public_call("anchor-check", 1)
    assert not writer._failed
    original = run.stores.tasks.read_latest_run_header(run.task_id)
    changed = replace(original, anchor=replace(original.anchor, event_id=uuid4()))
    monkeypatch.setattr(run.stores.tasks, "read_latest_run_header", lambda _: changed)
    try:
        with pytest.raises(TransientOutputUnavailable, match="source does not authorize"):
            writer._gate.issue()
        with pytest.raises(TransientOutputUnavailable, match="source does not authorize"):
            writer._gate.resolve(writer._auth)
    finally:
        writer.close()
        writer._port._client.close()


@pytest.mark.parametrize("valid", [False, True])
def test_native_fresh_binding_self_validation_and_valid_api_renewal(owned, monkeypatch, valid):
    from agent_core.domain.host_authority import HostGrantMismatchError
    from zebra_agent_api.session_binding import renew_task_binding_snapshot

    run, lease, recovery, binding, settings = setup(owned, monkeypatch)
    recovery.persist_with(run.recorder.append_draft)(
        HarnessEventDraft(
            EventType.MODEL_REQUEST_STARTED,
            EventActor.HARNESS,
            {"model_call_id": "renew-check", "attempt_number": 1},
        )
    )
    writer = compose_transient_output_factory(
        run.stores, dsn=owned[0], namespace=run.namespace, settings=settings
    )(recovery, lease)
    writer.start_public_call("renew-check", 1)
    assert not writer._failed
    original_auth = writer._auth
    if valid:
        context = binding.host_capability.host_context.model_copy(
            update={"grant_id": "renewed", "expires_at": datetime.now(UTC) + timedelta(minutes=6)}
        )
        changed = renew_task_binding_snapshot(
            binding, context, authority_issuer=binding.host_capability.authority_issuer
        )
    else:
        changed = binding.model_copy(
            update={
                "binding_revision": 2,
                "host_capability": binding.host_capability.model_copy(
                    update={"grant_digest": "0" * 64}
                ),
            }
        )
    save_task_binding(
        owned[0], deployment_namespace=run.namespace, binding=changed, expected_previous_revision=1
    )
    try:
        if valid:
            issued = writer._gate.issue()
            writer._gate.resolve(issued)
            assert issued.scope == original_auth.scope
        else:
            with pytest.raises(HostGrantMismatchError, match="Host authority conflicts"):
                writer._gate.issue()
            with pytest.raises(HostGrantMismatchError, match="Host authority conflicts"):
                writer._gate.resolve(original_auth)
    finally:
        writer.close()
        writer._port._client.close()


def test_native_actual_public_expression_is_ancillary_to_main_callback(owned, monkeypatch):
    from agent_core.harness.public_expression import PublicExpression

    run, lease, recovery, _, settings = setup(owned, monkeypatch)
    persist = recovery.persist_with(run.recorder.append_draft)
    persist(
        HarnessEventDraft(
            EventType.MODEL_REQUEST_STARTED,
            EventActor.HARNESS,
            {"model_call_id": "main-a", "attempt_number": 1},
        )
    )

    def complete(*args):
        return ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content='{"order":[0,1],"lead":"findings"}',
                created_at=datetime.now(UTC),
            )
        )

    expression = PublicExpression(
        complete,
        persist,
        max_calls=2,
        deadline_s=1,
        max_input_characters=1600,
        max_output_tokens=128,
    )
    assert expression.express(["fact1", "fact2"], chinese=False) is not None
    writer = compose_transient_output_factory(
        run.stores, dsn=owned[0], namespace=run.namespace, settings=settings
    )(recovery, lease)
    try:
        writer.start_public_call("main-a", 1)
        assert not writer._failed
        # A second actual ancillary request/response after activation must also
        # preserve fresh main-call authority without exposing ancillary content.
        assert expression.express(["fact1", "fact2"], chinese=False) is not None
        authority = writer._gate.issue()
        writer._gate.resolve(authority)
        assert authority.scope.generation.model_call_id == "main-a"
    finally:
        writer.close()
        writer._port._client.close()


@pytest.mark.parametrize("kind", ["ordinary", "unknown", "forged", "reused"])
def test_native_new_request_supersedes_or_rejects_ancillary_forgery(owned, monkeypatch, kind):
    from agent_integrations.redis_transient_output import TransientOutputUnavailable

    run, lease, recovery, _, settings = setup(owned, monkeypatch)
    persist = recovery.persist_with(run.recorder.append_draft)
    persist(
        HarnessEventDraft(
            EventType.MODEL_REQUEST_STARTED,
            EventActor.HARNESS,
            {"model_call_id": "main-b", "attempt_number": 1},
        )
    )
    writer = compose_transient_output_factory(
        run.stores, dsn=owned[0], namespace=run.namespace, settings=settings
    )(recovery, lease)
    writer.start_public_call("main-b", 1)
    assert not writer._failed
    gate, auth = writer._gate, writer._auth
    payload = {"model_call_id": "main-b" if kind == "reused" else "main-c", "attempt_number": 1}
    if kind != "ordinary":
        payload["purpose"] = "unknown" if kind == "unknown" else "public_expression"
    actor = EventActor.USER if kind == "forged" else EventActor.HARNESS
    if kind == "unknown":
        from agent_core.domain.events import SessionEvent

        # Deliberately malformed historical/native source bypasses the normal
        # closed purpose schema; the replay authority must still fail closed.
        event = SessionEvent(
            event_id=new_event_id(),
            created_at=datetime.now(UTC),
            session_id=run.session_id,
            sequence=run.recorder.session.current_sequence + 1,
            event_type=EventType.MODEL_REQUEST_STARTED,
            actor=actor,
            payload=payload,
        )
        run.stores.events.append(event)
        run.recorder.project_persisted_tail()
        recovery.catch_up()
    else:
        persist(HarnessEventDraft(EventType.MODEL_REQUEST_STARTED, actor, payload))
    try:
        with pytest.raises(TransientOutputUnavailable, match="superseded"):
            gate.issue()
        with pytest.raises(TransientOutputUnavailable, match="superseded"):
            gate.resolve(auth)
        # An old hook cannot find main-b behind a newer main/unknown/forged call.
        writer.start_public_call("main-b", 1)
        assert writer._failed
    finally:
        writer.close()
        writer._port._client.close()
