"""Native source/lease gates and real callback SQL; synthetic admission/Grant loaders.

Does not certify Host negotiation/signatures or an enabled production composition.
"""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelTextDelta
from agent_core.domain.stream_admission import (
    RunStreamAdmission,
    StreamCapabilities,
    StreamMode,
    TransientCapacityPolicy,
)
from agent_core.domain.transient_output import TransientGeneration
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.orchestration_events import model_response_event
from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy
from agent_core.ports.transient_output import TransientStreamScope
from agent_integrations.redis_transient_output import (
    RedisTransientOutput,
    TransientOutputUnavailable,
)
from agent_storage import PostgresLeaseStore
from zebra_agent_worker.progress_recovery import recover_worker_progress
from zebra_agent_worker.transient_output_runtime import TransientDeltaSink, WorkerTransientCallGate

from tests.stream_storage.native_environment import native_environment, seed
from tests.stream_storage.telemetry import Telemetry, phase


@pytest.fixture(scope="module")
def owned():
    dsn, url = (
        os.environ.get("ZEBRA_STREAM_TEST_POSTGRES_DSN"),
        os.environ.get("ZEBRA_STREAM_TEST_REDIS_URL"),
    )
    if not dsn or not url:
        pytest.skip("set private native PostgreSQL/Redis dependencies")
    with native_environment(dsn, url) as (scratch, client, fanout):
        yield scratch, client, fanout


def test_native_actual_public_callback_has_zero_sql_for_10_and_100_frames(owned, monkeypatch):
    dsn, client, fanout = owned
    run = seed(dsn, fanout, 1)
    leases = PostgresLeaseStore(dsn, deployment_namespace=run.namespace)
    lease = leases.get(run.session_id)
    progress_recovery = recover_worker_progress(
        tasks=run.stores.tasks,
        namespace=run.namespace,
        session_id=run.session_id,
        ownership_check=lambda: None,
    )
    admission = RunStreamAdmission(
        task_id=run.task_id,
        run_id="run",
        mode=StreamMode.TRANSIENT_V2,
        capacity_policy=TransientCapacityPolicy(),
        capacity_digest=TransientCapacityPolicy().digest,
        capabilities=StreamCapabilities(
            wire_version=2,
            provisional_draft_label=True,
            replace_message=True,
            reset_provisional=True,
            scoped_resume=True,
        ),
    )
    # A unique scratch table makes freshness observable, while keeping admission
    # negotiation and signed-Host verification explicitly outside this component proof.
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "CREATE TABLE writer_test_authority (admission text, grant_expiry timestamptz)"
        )
        connection.execute(
            "INSERT INTO writer_test_authority VALUES (%s,%s)",
            (admission.model_dump_json(), datetime.now(UTC) + timedelta(minutes=5)),
        )

    admission_fault = False

    def load_admission():
        if admission_fault:
            raise TimeoutError("initial native admission loader timed out")
        with psycopg.connect(dsn) as connection:
            value = connection.execute("SELECT admission FROM writer_test_authority").fetchone()[0]
        return RunStreamAdmission.model_validate_json(value)

    def fresh_grant(_):
        with psycopg.connect(dsn) as connection:
            value, valid = connection.execute(
                "SELECT grant_expiry, grant_expiry>clock_timestamp() FROM writer_test_authority"
            ).fetchone()
        if not valid:
            raise TransientOutputUnavailable("fresh Grant expired")
        return value

    active = []
    prefix = f"{fanout._key_prefix}:writer"
    port = RedisTransientOutput(
        client, resolve_authorization=lambda auth: active[-1].resolve(auth), key_prefix=prefix
    )
    writer = TransientDeltaSink(
        port,
        lambda call, attempt: open_gate(call, attempt),
        durable_anchor=lambda: progress_recovery.head.through_sequence,
    )

    def open_gate(call, attempt):
        gate = WorkerTransientCallGate(
            scope=TransientStreamScope(
                deployment_namespace=run.namespace,
                authority_scope=OpaqueAuthorityScope(
                    authority_issuer="fixture", namespace_id="host"
                ),
                generation=TransientGeneration(
                    task_id=run.task_id,
                    segment_id=run.session_id,
                    turn_id=uuid4(),
                    run_id="run",
                    attempt_number=attempt,
                    model_call_id=call,
                    message_id=f"message:{call}",
                    generation_id=str(uuid4()),
                    lease_fence=lease.fence.fencing_token,
                ),
            ),
            fence=lease.fence,
            request_sequence=progress_recovery.head.through_sequence,
            tasks=run.stores.tasks,
            leases=leases,
            load_admission=load_admission,
            fresh_grant_expiry=fresh_grant,
        )
        active.append(gate)
        return gate

    from tests.agent_core.test_transient_output_contract import authorization, generation

    initial = authorization(generation()).scope.model_copy(
        update={"deployment_namespace": run.namespace}
    )
    port.seal_capacity(initial, admission.capacity_policy, old_keys=(),
                       old_writers_quiescent=True, old_ttl_drained=True)
    progress = ProgressiveEventSink(
        writer.wrap(progress_recovery.persist_with(run.recorder.append_draft)),
        user_input="x",
        policy=PublicOutputPolicy(expression_max_calls=0),
        recovery_state=progress_recovery.head.state,
        output_published=progress_recovery.output_published,
        receipts_covered=progress_recovery.receipts_covered,
    )
    telemetry = Telemetry()

    class Provider:
        def complete(self, *_args, **_kwargs):
            raise AssertionError("expected actual public callback")

        def complete_stream(self, _messages, *, tools=(), on_text_delta):
            # Activation is already complete before provider callback starts.
            with phase("native/provider-text"):
                for index in range(self.count):
                    on_text_delta(ModelTextDelta(index=index, content=" ordinary public "))
            return ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Full authoritative response",
                    created_at=datetime.now(UTC),
                )
            )

    provider = Provider()
    step = HarnessModelStep(event_sink=progress, public_call_started=writer.start_public_call)
    provider_counts = []
    with telemetry.installed():
        for count in (10, 100):
            provider.count = count
            completion = step.request_completion([], provider, allow_tools=True)
            assert not writer._failed
            assert progress._model_spoke
            assert writer._offset == count
            progress(model_response_event(completion, attempt_number=1, response_stage="candidate"))
            assert active[-1]._closed
            provider_counts.append(
                sum(
                    value
                    for key, value in telemetry.calls.items()
                    if "/native/provider-text/sql:" in key
                )
            )
    assert provider_counts == [0, 0]
    # Initial uncertainty never opts a Run back into v1 content persistence.
    for failure in ("admission", "header"):
        provider.count = 10
        admission_fault = failure == "admission"
        with monkeypatch.context() as patcher:
            if failure == "header":

                def header_timeout(*_args, **_kwargs):
                    raise TimeoutError("resolved native v2 source header timed out")

                patcher.setattr(run.stores.tasks, "read_task_header", header_timeout)
            with telemetry.installed():
                completion = step.request_completion([], provider, allow_tools=True)
        assert writer._failed and active[-1]._closed
        assert writer._offset == 0
        progress(model_response_event(completion, attempt_number=1, response_stage="candidate"))
    admission_fault = False
    assert not any(
        value for key, value in telemetry.calls.items() if "/native/provider-text/sql:" in key
    )
    events = run.stores.events.list_for_session(run.session_id)
    assert sum(event.event_type is EventType.MODEL_REQUEST_STARTED for event in events) == 4
    assert sum(event.event_type is EventType.MODEL_RESPONSE_RECEIVED for event in events) == 4
    assert not any(event.event_type is EventType.MODEL_RESPONSE_DELTA for event in events)
    restored = recover_worker_progress(
        tasks=run.stores.tasks,
        namespace=run.namespace,
        session_id=run.session_id,
        ownership_check=lambda: None,
    )
    assert restored.head.state.model_spoke
    with pytest.raises(TransientOutputUnavailable, match="closed"):
        active[-1].issue()
    # Fresh native lease authority catches revocation without trusting require_owned().
    previous = active[-1]
    reconstructed = WorkerTransientCallGate(
        scope=previous.scope,
        fence=previous.fence,
        request_sequence=previous.request_sequence,
        tasks=run.stores.tasks,
        leases=leases,
        load_admission=load_admission,
        fresh_grant_expiry=fresh_grant,
    )
    client.delete(*port._keys(previous.scope))
    with pytest.raises(TransientOutputUnavailable, match="completed or reused"):
        reconstructed.issue()
    progress.close()
    writer.close()
    run.recorder.append_draft(
        HarnessEventDraft(
            EventType.MODEL_REQUEST_STARTED,
            EventActor.HARNESS,
            {"model_call_id": "old-attempt", "attempt_number": 1},
        )
    )
    progress_recovery.catch_up()
    old_attempt = open_gate("old-attempt", 1)
    old_authority = old_attempt.issue()
    run.recorder.append_draft(
        HarnessEventDraft(
            EventType.HARNESS_ATTEMPT_STARTED, EventActor.HARNESS, {"attempt_number": 2}
        )
    )
    with pytest.raises(TransientOutputUnavailable, match="Attempt was superseded"):
        old_attempt.resolve(old_authority)
    run.recorder.append_draft(
        HarnessEventDraft(
            EventType.MODEL_REQUEST_STARTED,
            EventActor.HARNESS,
            {"model_call_id": "revocation-check", "attempt_number": 2},
        )
    )
    progress_recovery.catch_up()
    gate = open_gate("revocation-check", 2)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE writer_test_authority SET grant_expiry=clock_timestamp()")
    with pytest.raises(TransientOutputUnavailable, match="Grant expired"):
        gate.issue()
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE writer_test_authority SET grant_expiry=clock_timestamp()+interval '5 minutes'"
        )
    first = gate.issue()
    leases.release(run.session_id, fence=lease.fence)
    with pytest.raises(TransientOutputUnavailable, match="full lease"):
        gate.resolve(first)
    reacquired = leases.acquire(
        run.session_id, owner_instance_id="new-worker", ttl=timedelta(seconds=60)
    )
    assert reacquired.fence != lease.fence
    with pytest.raises(TransientOutputUnavailable, match="full lease"):
        gate.issue()
    progress.close()
    writer.close()
