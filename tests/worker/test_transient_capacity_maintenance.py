"""Owned native collection, two Worker objects, deadline and provisional fallback."""

import json
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from unittest.mock import Mock

import pytest
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.stream_admission import TransientCapacityPolicy
from agent_core.harness.models import HarnessEventDraft
from agent_integrations.redis_transient_deadlines import redis_io_deadline
from agent_integrations.redis_transient_output import RedisTransientOutput
from zebra_agent_config import load_settings
from zebra_agent_worker.transient_capacity_maintenance import TransientCapacityMaintenance
from zebra_agent_worker.transient_output_composition import compose_transient_output_factory

from tests.worker.test_transient_output_composition_native import owned, setup

# Explicit fixture re-export survives Ruff; imports retain the original native scope.
owned = owned


def test_two_actual_worker_compositions_cap_and_durable_completion(owned, monkeypatch):
    run, lease, recovery, _, settings = setup(owned, monkeypatch)
    run.recorder.append(EventType.MODEL_REQUEST_STARTED, EventActor.HARNESS,
                        {"model_call_id": "capacity-worker", "attempt_number": 1})
    recovery.catch_up()
    factory = compose_transient_output_factory(
        run.stores, dsn=owned[0], namespace=run.namespace, settings=settings)
    writers = [factory(recovery, lease), factory(recovery, lease)]
    assert all(writer is not None for writer in writers)
    outcomes = []
    activate = RedisTransientOutput.activate

    def measured_activate(port, auth):
        try:
            value = activate(port, auth)
            outcomes.append("ok")
            return value
        except Exception as error:
            outcomes.append(type(error).__name__)
            raise

    monkeypatch.setattr(RedisTransientOutput, "activate", measured_activate)
    # Two real native Worker compositions share the exact canonical call/full fence.
    with ThreadPoolExecutor(2) as threads:
        list(threads.map(lambda w: w.start_public_call("capacity-worker", 1), writers))
    assert any(not writer._failed for writer in writers)
    scopes = [writer._gate.scope for writer in writers if writer._gate is not None]
    assert len(scopes) >= 1
    # Both reservations are retained even when the final CAS fences one contender.
    ledger = writers[0]._port._capacity_keys(scopes[0])[0]
    client = writers[0]._port._client
    assert len(outcomes) == 2 and "ok" in outcomes
    assert json.loads(client.hget(ledger, "deployment")) == [2*65536, 0, 2]
    assert client.zcard(ledger + ":due") == 2
    assert all(client.xlen(writer._port._keys(scope)[1]) == 0
               for writer in writers for scope in scopes)
    saved = []
    for writer in writers:
        callback = writer.wrap(saved.append)
        callback(HarnessEventDraft(EventType.MODEL_RESPONSE_DELTA, EventActor.HARNESS,
                                   {"model_call_id": "capacity-worker", "attempt_number": 1,
                                    "content_delta": "draft"}))
        callback(HarnessEventDraft(EventType.MODEL_RESPONSE_RECEIVED, EventActor.HARNESS,
                                   {"model_call_id": "capacity-worker", "attempt_number": 1}))
        writer.close()
    assert len(saved) == 2
    assert all(event.event_type is EventType.MODEL_RESPONSE_RECEIVED for event in saved)


def test_native_maintenance_rate_two_instances_gc_release_once_and_parent(owned, monkeypatch):
    run, lease, recovery, _, settings = setup(owned, monkeypatch)
    writer = compose_transient_output_factory(
        run.stores, dsn=owned[0], namespace=run.namespace, settings=settings)(recovery, lease)
    assert writer is not None
    run.recorder.append(EventType.MODEL_REQUEST_STARTED, EventActor.HARNESS,
                        {"model_call_id": "gc-worker", "attempt_number": 1})
    recovery.catch_up()
    writer.start_public_call("gc-worker", 1)
    assert not writer._failed
    scope = writer._gate.scope
    port = writer._port
    policy = writer._auth.capacity_policy
    ledger, due, record = port._capacity_keys(scope)
    port._client.hset(record, "dirty", "gc")
    port._client.zadd(due, {record: 0})
    enabled = load_settings({"ZEBRA_STREAM_CAPACITY_POLICY": policy.model_dump_json()})
    second = RedisTransientOutput.from_url(owned[3], resolve_authorization=Mock(),
                                          key_prefix=port._prefix)
    workers = [TransientCapacityMaintenance(port, run.namespace, enabled),
               TransientCapacityMaintenance(second, run.namespace, enabled)]
    with ThreadPoolExecutor(2) as threads:
        assert sum(threads.map(lambda w: w.tick(), workers)) == 1
    assert json.loads(port._client.hget(ledger, "deployment")) == [0, 0, 0]
    assert workers[0].tick() == workers[1].tick() == 0
    # A shorter real inherited deadline refuses work; no increased socket timeout.
    workers[0]._next = 0
    with pytest.raises(TimeoutError), redis_io_deadline(monotonic()-0.001):
        workers[0].tick()
    writer.close()
    for worker in workers:
        worker.close()
    assert all(worker._closed for worker in workers)


@pytest.mark.parametrize("private", [{}, None])
def test_actual_gate_private_source_denies_before_quota_mutation(owned, monkeypatch, private):
    run, lease, recovery, _, settings = setup(owned, monkeypatch)
    writer = compose_transient_output_factory(
        run.stores, dsn=owned[0], namespace=run.namespace, settings=settings)(recovery, lease)
    run.recorder.append(EventType.MODEL_REQUEST_STARTED, EventActor.HARNESS,
                        {"model_call_id": "private-worker", "attempt_number": 1})
    recovery.catch_up()
    from tests.agent_core.test_transient_output_contract import authorization, generation
    scope = authorization(generation()).scope.model_copy(
        update={"deployment_namespace": run.namespace})
    ledger, due, _ = writer._port._capacity_keys(scope)
    initial = (writer._port._client.hgetall(ledger), writer._port._client.zrange(due, 0, -1))
    run.recorder.append(EventType.COVERAGE_RUN_CANCELLED, EventActor.HARNESS,
                        {"coverage_admission": private})
    recovery.catch_up()
    header = run.stores.tasks.read_task_header(run.task_id, require_source_coverage=True)
    assert header.strict_coverage
    writer.start_public_call("private-worker", 1)
    assert (writer._port._client.hgetall(ledger),
            writer._port._client.zrange(due, 0, -1)) == initial
    saved = []
    writer.wrap(saved.append)(HarnessEventDraft(
        EventType.MODEL_RESPONSE_DELTA, EventActor.HARNESS,
        {"model_call_id": "private-worker", "attempt_number": 1, "content_delta": "secret"}))
    assert saved == []
    writer.close()


def test_native_capacity_exhaustion_commits_real_response_and_terminal_no_delta(owned, monkeypatch):
    from datetime import UTC, datetime

    from agent_core.domain.identifiers import new_message_id
    from agent_core.domain.messages import MessageRole, SessionMessage
    from agent_core.domain.modeling import ModelCompletion, ModelTextDelta
    from agent_core.harness.model_step import HarnessModelStep
    from agent_core.harness.orchestration_events import model_response_event
    from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy

    run, lease, recovery, _, settings = setup(
        owned, monkeypatch, capacity_policy=TransientCapacityPolicy(generation_rows=1))
    writer = compose_transient_output_factory(
        run.stores, dsn=owned[0], namespace=run.namespace, settings=settings)(recovery, lease)
    progress = ProgressiveEventSink(writer.wrap(recovery.persist_with(run.recorder.append_draft)),
        user_input="x", policy=PublicOutputPolicy(expression_max_calls=0),
        recovery_state=recovery.head.state, output_published=recovery.output_published,
        receipts_covered=recovery.receipts_covered)

    class Provider:
        def complete_stream(self, _messages, *, tools=(), on_text_delta):
            for index in range(2):
                on_text_delta(ModelTextDelta(index=index, content=" " + "x"*12000))
            return ModelCompletion(assistant_message=SessionMessage(
                message_id=new_message_id(), role=MessageRole.ASSISTANT,
                content="Authoritative completion survives quota exhaustion",
                created_at=datetime.now(UTC)))

    step = HarnessModelStep(event_sink=progress, public_call_started=writer.start_public_call)
    complete = step.request_completion([], Provider(), allow_tools=True)
    assert writer._failed
    progress(model_response_event(complete, attempt_number=1, response_stage="candidate"))
    run.recorder.append(EventType.SESSION_COMPLETED, EventActor.HARNESS, {})
    events = run.stores.events.list_for_session(run.session_id)
    assert sum(event.event_type is EventType.MODEL_RESPONSE_RECEIVED for event in events) == 1
    assert events[-1].event_type is EventType.SESSION_COMPLETED
    assert not any(event.event_type is EventType.MODEL_RESPONSE_DELTA for event in events)
    writer.close()
    progress.close()


def test_native_old_v2_missing_policy_commits_response_without_delta(owned, monkeypatch):
    from agent_integrations.run_stream_admission import load_run_stream_admission

    from tests.agent_core.test_transient_output_contract import authorization, generation

    original_setup = setup
    prepared = []
    prefix = f"{owned[2]._key_prefix}:admission"
    before_keys = set(owned[1].scan_iter(match=prefix+":*"))

    def old_setup(endpoints, patcher, **kwargs):
        result = original_setup(endpoints, patcher, missing_policy=True, **kwargs)
        prepared.append(result[0])
        return result

    monkeypatch.setitem(globals(), "setup", old_setup)
    # Same actual Harness/native canonical response oracle; only server metadata is old.
    test_native_capacity_exhaustion_commits_real_response_and_terminal_no_delta(owned, monkeypatch)
    run = prepared[0]
    admission = load_run_stream_admission(run.stores.tasks, run.task_id, "run-v2")
    assert admission.mode.value == "transient_v2" and admission.capacity_policy is None
    port = RedisTransientOutput(owned[1], resolve_authorization=Mock(), key_prefix=prefix)
    scope = authorization(generation()).scope.model_copy(
        update={"deployment_namespace": run.namespace})
    assert owned[1].exists(*port._capacity_keys(scope)[:2]) == 0
    assert set(owned[1].scan_iter(match=prefix+":*")) == before_keys


def test_native_capacity_full_tick_command_cpu_latency_memory_accounting(
    owned, monkeypatch, record_property,
):
    from collections import Counter
    from time import sleep

    from redis import Redis
    from zebra_agent_worker.worker_loop_service import WorkerLoopService

    from tests.agent_core.test_transient_output_contract import frame
    from tests.stream_storage.telemetry import Telemetry, phase

    telemetry, commands, walls = Telemetry(), Counter(), []
    execute = Redis.execute_command

    def measured(client, *args, **kwargs):
        name = str(args[0]).split()[0].upper()
        commands[name] += 1
        started = monotonic()
        try:
            return execute(client, *args, **kwargs)
        finally:
            if name == "EVAL":
                walls.append(monotonic()-started)

    before_cpu = owned[1].info("commandstats").get("cmdstat_eval", {})
    monkeypatch.setattr(Redis, "execute_command", measured)
    with telemetry.installed():
        run, lease, recovery, _, settings = setup(owned, monkeypatch)
        run.recorder.append(EventType.MODEL_REQUEST_STARTED, EventActor.HARNESS,
                            {"model_call_id": "cost-worker", "attempt_number": 1})
        recovery.catch_up()
        writer = compose_transient_output_factory(
            run.stores, dsn=owned[0], namespace=run.namespace, settings=settings)(recovery, lease)
        with phase("quota-activation"):
            writer.start_public_call("cost-worker", 1)
        assert not writer._failed
        port, auth = writer._port, writer._auth
        for offset in range(32):
            with phase("quota-frames"):
                port.publish(auth, frame(auth.scope.generation, offset=offset,
                                        content_delta="x"*12000))
        ledger, due, record = port._capacity_keys(auth.scope)
        memory_before = port._client.info("memory")
        port._client.hset(record, "dirty", "gc")
        port._client.zadd(due, {record: 0})
        enabled = load_settings(
            {"ZEBRA_STREAM_CAPACITY_POLICY": auth.capacity_policy.model_dump_json()}
        )
        maintenance = TransientCapacityMaintenance(port, run.namespace, enabled)
        projection = Mock()
        projection.list_ready_sessions.return_value = []
        service = WorkerLoopService(projection_store=projection, execution_service=Mock(),
                                    transient_capacity=maintenance)
        with phase("quota-maintenance"):
            service.maintenance_once(worker_id="cost", batch_size=1, lease_ttl_seconds=30)
            service.poll_once(worker_id="cost", batch_size=1, lease_ttl_seconds=30)
        assert port._client.exists(*port._keys(auth.scope)[1:]) == 0
        assert json.loads(port._client.hget(ledger, "deployment")) == [0, 0, 0]
        samples = []
        for _ in range(3):
            memory = port._client.info("memory")
            samples.append([memory["used_memory"], memory["used_memory_rss"]])
            sleep(0.05)
        after_cpu = owned[1].info("commandstats").get("cmdstat_eval", {})
        writer.close()
        service.drain()
    assert not any(v for k, v in telemetry.calls.items() if "/quota-frames/sql:" in k)
    record_property("all_client_sql", sum(v for k, v in telemetry.calls.items() if "/sql:" in k))
    record_property("all_pg_sockets", sum(v for k, v in telemetry.calls.items()
                                         if k.endswith("/new_pg_socket")))
    record_property("redis_client_command_counts", json.dumps(dict(commands), sort_keys=True))
    record_property("owned_redis_global_eval_cpu_usec", after_cpu.get("usec", 0)-
                    before_cpu.get("usec", 0))
    record_property("owned_redis_global_eval_calls", after_cpu.get("calls", 0)-
                    before_cpu.get("calls", 0))
    record_property("client_eval_wall_samples_seconds", json.dumps(walls))
    record_property("memory_global_before_used_rss", json.dumps([
        memory_before["used_memory"], memory_before["used_memory_rss"]]))
    record_property("memory_global_after_3samples_used_rss", json.dumps(samples))
    record_property("measurement_boundary", "UNLINK logical release; global memory not isolated; "
                    "setup/activation/32frames/two maintenance entrances included; "
                    "memory/child/client-effect/background lease renewal not configured")
