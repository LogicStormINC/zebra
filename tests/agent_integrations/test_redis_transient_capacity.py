"""Real standalone Redis retained accounting, indexed recovery and lane races."""

import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

import pytest
from agent_core.domain.stream_admission import TransientCapacityPolicy
from agent_core.ports.transient_output import TransientResumeCursor
from agent_integrations import redis_transient_capacity as scripts
from agent_integrations.redis_transient_output import (
    RedisTransientOutput,
    TransientOutputUnavailable,
)
from agent_integrations.redis_transient_scripts import ACTIVATE, INVALIDATE, PUBLISH, SNAPSHOT
from redis import Redis
from redis.exceptions import ResponseError

from tests.agent_core.test_transient_output_contract import authorization, frame, generation


@pytest.fixture
def native():
    url = os.environ.get("ZEBRA_STREAM_TEST_REDIS_URL")
    if not url:
        pytest.skip("owned native Redis required")
    client = Redis.from_url(url, decode_responses=True, socket_timeout=2)
    prefix = f"zebra:capacity:test:{uuid4().hex}"
    issued = []
    resolves = []

    def resolve(auth):
        resolves.append(auth)
        if not any(auth is entry for entry in issued):
            raise TransientOutputUnavailable("unknown actual gate")

    def adapter():
        return RedisTransientOutput(
            client, resolve_authorization=resolve, key_prefix=prefix,
            read_authority=lambda _: datetime.now(UTC)+timedelta(seconds=30),
        )

    port = adapter()

    def issue(policy=None, *, base=None, generation_changes=None, **scope_changes):
        policy = policy or TransientCapacityPolicy()
        auth = authorization(generation()) if base is None else base
        gen = auth.scope.generation.model_copy(
            update={"generation_id": str(uuid4()), **(generation_changes or {})})
        scope = auth.scope.model_copy(update={"generation": gen, **scope_changes})
        auth = auth.model_copy(update={"scope": scope, "capacity_policy": policy,
                                     "capacity_digest": policy.digest})
        issued.append(auth)
        return auth

    try:
        yield port, client, issue, adapter, resolves
    finally:
        # Only this fixture's owned unique prefix; no global cleanup/service operations.
        for key in client.scan_iter(match=prefix+":*"):
            client.delete(key)
        client.close()


def seal(port, auth):
    port.seal_capacity(auth.scope, auth.capacity_policy, old_keys=(),
                       old_writers_quiescent=True, old_ttl_drained=True)


def charged(port, client, auth):
    return json.loads(client.hget(port._capacity_keys(auth.scope)[0], "deployment"))


def test_first_reservation_gate_seal_and_exact_charge_duplicate(native):
    port, client, issue, _, resolves = native
    auth = issue()
    keys_before = client.dbsize()
    with pytest.raises(TransientOutputUnavailable, match="unknown actual gate"):
        port.activate(auth.model_copy())
    assert client.dbsize() == keys_before
    with pytest.raises(TransientOutputUnavailable, match="unsealed"):
        port.activate(auth)
    assert client.dbsize() == keys_before
    seal(port, auth)
    port.activate(auth)
    assert resolves[-2:] == [auth, auth]
    assert charged(port, client, auth) == [65536, 0, 1]
    first = frame(auth.scope.generation)
    cursor = port.publish(auth, first)
    expected = [65536+len(first.wire_bytes())+512, 1, 1]
    assert charged(port, client, auth) == expected
    assert port.publish(auth, first) == cursor
    assert charged(port, client, auth) == expected
    port.activate(auth)
    assert charged(port, client, auth) == expected
    assert client.hget(port._keys(auth.scope)[0], "generations") == "1"


@pytest.mark.parametrize("level", ["run", "tenant", "deployment"])
def test_real_two_worker_lanes_race_retained_slot_limit(native, level):
    port, client, issue, adapter, _ = native
    policy = TransientCapacityPolicy.model_validate({level+"_slots": 1})
    first = issue(policy)
    second = issue(policy, base=first)
    # Different Segment makes different lane, but SAME Run quota identity.
    second = second.model_copy(update={"scope": second.scope.model_copy(update={
        "generation": second.scope.generation.model_copy(update={"segment_id": uuid4()})})})
    # Fixture registered handles are necessary; registering the replacement is explicit.
    issue_callback = port._resolve
    port._resolve = lambda a: None if a is second else issue_callback(a)
    other = adapter()
    other._resolve = port._resolve
    seal(port, first)
    barrier = Barrier(2)

    def activate(pair):
        worker, auth = pair
        barrier.wait(timeout=2)
        try:
            worker.activate(auth)
            return True
        except TransientOutputUnavailable:
            return False

    with ThreadPoolExecutor(2) as workers:
        results = list(workers.map(activate, [(port, first), (other, second)]))
    assert sum(results) == 1
    assert charged(port, client, first) == [65536, 0, 1]
    assert client.zcard(port._capacity_keys(first.scope)[1]) <= policy.deployment_slots


def test_replacement_retains_old_body_charge_until_gc_and_hard_ttl(native):
    port, client, issue, _, _ = native
    policy = TransientCapacityPolicy(active_seconds=2, ended_seconds=1)
    first = issue(policy)
    seal(port, first)
    port.activate(first)
    port.publish(first, frame(first.scope.generation))
    old_keys = port._keys(first.scope)
    expiry = client.pexpiretime(old_keys[1])
    second = issue(policy, base=first)
    port.activate(second)
    assert charged(port, client, first)[2] == 2
    assert client.exists(old_keys[1]) == 1
    port.invalidate(first.scope)
    assert charged(port, client, first)[2] == 2
    assert client.pexpiretime(old_keys[1]) <= expiry
    port.activate(second)
    assert client.hget(port._keys(second.scope)[0], "generations") == "2"
    sleep(1.05)
    assert port.collect_capacity(first.scope, policy) == 1
    assert client.exists(old_keys[1], old_keys[2]) == 0
    assert charged(port, client, second)[2] == 1
    assert port.collect_capacity(first.scope, policy) == 0


@pytest.mark.parametrize("operation", ["snapshot", "activate", "publish", "invalidate"])
def test_partial_lua_writes_dirty_failclosed_indexed_recovery(native, monkeypatch, operation):
    port, client, issue, _, _ = native
    auth = issue()
    seal(port, auth)
    if operation in {"publish", "invalidate"}:
        port.activate(auth)
        port.publish(auth, frame(auth.scope.generation))
    originals = {"snapshot": SNAPSHOT, "activate": ACTIVATE, "publish": PUBLISH,
                 "invalidate": INVALIDATE}
    original_eval = client.eval
    selected = originals[operation]

    def fault(script, *args):
        if script == selected:
            # Real Lua error AFTER retained charge/body mutation; Redis does not roll back.
            if operation == "snapshot":
                marker = "redis.call('HSET',record,'dirty','0')"
                at = script.rfind(marker)
                script = script[:at] + "redis.call('INCR',KEYS[5])" + script[at+len(marker):]
            else:
                at = script.rfind("finish()")
                script = script[:at] + "redis.call('INCR',KEYS[5])\n" + script[at:]
        return original_eval(script, *args)

    monkeypatch.setattr(client, "eval", fault)
    with pytest.raises(TransientOutputUnavailable):
        if operation in {"snapshot", "activate"}:
            port.activate(auth)
        elif operation == "publish":
            port.publish(auth, frame(auth.scope.generation, offset=1))
        else:
            port.invalidate(auth.scope)
    monkeypatch.setattr(client, "eval", original_eval)
    assert charged(port, client, auth)[2] == 1  # No early refund on uncertainty.
    record = port._capacity_keys(auth.scope)[2]
    assert client.hget(record, "dirty") != "0"
    cursor = TransientResumeCursor(scope=auth.scope, durable_sequence=0)
    assert port.read_after(scope=auth.scope, cursor=cursor,
                           authorized_until=auth.expires_at).resync_required
    with pytest.raises(TransientOutputUnavailable, match="dirty"):
        port.activate(auth)
    assert port.collect_capacity(auth.scope, auth.capacity_policy) == 1
    assert charged(port, client, auth) == [0, 0, 0]
    assert client.exists(*port._keys(auth.scope)[1:]) == 0
    assert port.collect_capacity(auth.scope, auth.capacity_policy) == 0


@pytest.mark.parametrize("after_release", [False, True])
def test_gc_actual_partial_failure_delete_before_release_and_once(
    native, monkeypatch, after_release,
):
    port, client, issue, _, _ = native
    auth = issue()
    seal(port, auth)
    port.activate(auth)
    port.publish(auth, frame(auth.scope.generation))
    before = charged(port, client, auth)
    ledger, due, record = port._capacity_keys(auth.scope)
    client.hset(record, "dirty", "gc")
    client.zadd(due, {record: 0})  # Exact owned recovery intent, no early-expiry bypass.
    original_eval = client.eval

    def fault(script, *args):
        if script == scripts.GC:
            marker = ("redis.call('HSET',KEYS[1],unpack(edits))" if after_release
                      else "redis.call('UNLINK',keys[2],keys[3])")
            script = script.replace(marker, marker+"\nredis.call('INCR',KEYS[1])", 1)
        return original_eval(script, *args)

    monkeypatch.setattr(client, "eval", fault)
    with pytest.raises(ResponseError):
        port.collect_capacity(auth.scope, auth.capacity_policy)
    assert client.exists(*port._keys(auth.scope)[1:]) == 0
    assert charged(port, client, auth) == ([0, 0, 0] if after_release else before)
    monkeypatch.setattr(client, "eval", original_eval)
    assert port.collect_capacity(auth.scope, auth.capacity_policy) == 1
    assert charged(port, client, auth) == [0, 0, 0]
    assert client.zcard(due) == 0 and client.exists(record) == 0


def test_epoch_wrong_types_lost_ledger_and_old_key_cutover(native):
    port, client, issue, _, _ = native
    auth = issue()
    old = port._keys(auth.scope)[1]
    client.set(old, "old body")
    with pytest.raises(TransientOutputUnavailable):
        port.seal_capacity(auth.scope, auth.capacity_policy, old_keys=(old,),
                           old_writers_quiescent=True, old_ttl_drained=True)
    client.delete(old)
    seal(port, auth)
    client.set(port._keys(auth.scope)[2], "wrong type")
    before = charged(port, client, auth)
    with pytest.raises(TransientOutputUnavailable, match="key_type"):
        port.activate(auth)
    assert charged(port, client, auth) == before
    client.delete(port._keys(auth.scope)[2])
    port.activate(auth)
    port.publish(auth, frame(auth.scope.generation))
    ledger, _, _ = port._capacity_keys(auth.scope)
    client.delete(ledger)
    with pytest.raises(TransientOutputUnavailable, match="unsealed"):
        port.activate(auth)
    with pytest.raises(TransientOutputUnavailable):
        seal(port, auth)
    assert client.exists(port._keys(auth.scope)[1]) == 1


def test_exact_row_byte_duplicate_at_cap_and_bounded_cost(native, record_property):
    port, client, issue, _, _ = native
    policy = TransientCapacityPolicy(generation_rows=1, run_rows=1)
    auth = issue(policy)
    seal(port, auth)
    start = monotonic()
    port.activate(auth)
    first = frame(auth.scope.generation)
    cursor = port.publish(auth, first)
    assert port.publish(auth, first) == cursor
    with pytest.raises(TransientOutputUnavailable, match="capacity"):
        port.publish(auth, frame(auth.scope.generation, offset=1))
    elapsed = monotonic()-start
    record_property("actual_lifecycle_seconds", elapsed)
    record_property("charged_bytes", charged(port, client, auth)[0])
    record_property("redis_used_memory_rss_global_not_quota",
                    client.info("memory")["used_memory_rss"])
    assert charged(port, client, auth)[1:] == [1, 1]


def _child_activate(prefix, raw, barrier, result):
    from agent_core.ports.transient_output import TransientWriterAuthorization
    auth = TransientWriterAuthorization.model_validate_json(raw)
    client = Redis.from_url(os.environ["ZEBRA_STREAM_TEST_REDIS_URL"],
                            decode_responses=True, socket_timeout=2)
    port = RedisTransientOutput(client, resolve_authorization=lambda candidate: (
        None if candidate is auth else (_ for _ in ()).throw(ValueError("unknown handle"))),
        key_prefix=prefix)
    barrier.wait(timeout=5)
    try:
        port.activate(auth)
        result.put("ok")
    except TransientOutputUnavailable:
        result.put("denied")
    finally:
        port.close()


def test_real_two_process_atomic_slot_race(native):
    port, client, issue, _, _ = native
    policy = TransientCapacityPolicy(run_slots=1)
    first = issue(policy)
    second = issue(policy, base=first)
    seal(port, first)
    context = multiprocessing.get_context("spawn")
    barrier, result = context.Barrier(2), context.Queue()
    children = [context.Process(target=_child_activate,
                args=(port._prefix, auth.model_dump_json(), barrier, result))
                for auth in (first, second)]
    try:
        for child in children:
            child.start()
        outcomes = [result.get(timeout=10), result.get(timeout=10)]
        for child in children:
            child.join(5)
        assert all(child.exitcode == 0 for child in children)
        assert sorted(outcomes) == ["denied", "ok"]
        assert charged(port, client, first) == [65536, 0, 1]
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(2)
        result.close()


def test_256_retained_empty_reservations_257_denied(native):
    port, client, issue, _, _ = native
    policy = TransientCapacityPolicy(run_slots=256, tenant_slots=512)
    base = issue(policy)
    seal(port, base)
    for _ in range(256):
        auth = issue(policy, base=base)
        port.activate(auth)
    assert charged(port, client, base) == [256*65536, 0, 256]
    with pytest.raises(TransientOutputUnavailable, match="capacity"):
        port.activate(issue(policy, base=base))
    assert charged(port, client, base)[2] == 256
    assert client.hget(port._keys(base.scope)[0], "generations") == "256"


@pytest.mark.parametrize("operation", ["activate", "publish"])
def test_actual_lost_reply_does_not_recharge(native, monkeypatch, operation):
    from redis.exceptions import ConnectionError
    port, client, issue, _, _ = native
    auth = issue()
    seal(port, auth)
    if operation == "publish":
        port.activate(auth)
    original_eval = client.eval
    dropped = False

    def lost(script, *args):
        nonlocal dropped
        value = original_eval(script, *args)
        target = ACTIVATE if operation == "activate" else PUBLISH
        if script == target and not dropped:
            dropped = True
            raise ConnectionError("injected lost reply")
        return value

    monkeypatch.setattr(client, "eval", lost)
    with pytest.raises(TransientOutputUnavailable):
        if operation == "activate":
            port.activate(auth)
        else:
            port.publish(auth, frame(auth.scope.generation))
    before = charged(port, client, auth)
    if operation == "activate":
        port.activate(auth)
    else:
        port.publish(auth, frame(auth.scope.generation))
    assert dropped and charged(port, client, auth) == before


def test_missing_aggregate_field_and_epoch_conflict_failclosed(native):
    port, client, issue, _, _ = native
    auth = issue()
    seal(port, auth)
    port.activate(auth)
    before = charged(port, client, auth)
    ledger = port._capacity_keys(auth.scope)[0]
    run_field = next(key for key in client.hkeys(ledger) if key.startswith("run:"))
    client.hdel(ledger, run_field)
    with pytest.raises(TransientOutputUnavailable, match="corrupt"):
        port.activate(issue(base=auth))
    assert charged(port, client, auth) == before
    conflicting = issue(TransientCapacityPolicy(epoch="another"), base=auth)
    with pytest.raises(TransientOutputUnavailable, match="unsealed"):
        port.activate(conflicting)
    with pytest.raises(TransientOutputUnavailable):
        seal(port, conflicting)


@pytest.mark.parametrize("level", ["generation", "run", "tenant", "deployment"])
@pytest.mark.parametrize("dimension", ["bytes", "rows"])
def test_all_exact_byte_row_caps_and_duplicate_at_boundary(native, level, dimension):
    port, client, issue, _, _ = native
    auth = issue()
    first = frame(auth.scope.generation)
    maximum = (len(first.wire_bytes()) if level == "generation"
               else 65536+len(first.wire_bytes())+512)
    policy = TransientCapacityPolicy.model_validate({level+"_"+dimension:
                                                     maximum if dimension == "bytes" else 1})
    auth = issue(policy, base=auth)
    # Serialized scope length is stable: replacing a UUID generation preserves its byte count.
    first = frame(auth.scope.generation)
    seal(port, auth)
    port.activate(auth)
    cursor = port.publish(auth, first)
    assert port.publish(auth, first) == cursor
    with pytest.raises(TransientOutputUnavailable, match="capacity"):
        port.publish(auth, frame(auth.scope.generation, offset=1))
    assert client.xlen(port._keys(auth.scope)[1]) == 1
    assert charged(port, client, auth)[1:] == [1, 1]


def test_native_real_redis_reply_stall_gc_parent_deadline(native):
    from agent_integrations.redis_transient_deadlines import redis_io_deadline
    from redis.exceptions import TimeoutError as RedisTimeoutError

    from tests.agent_runtime.test_stream_hint_relay import _ReplyProxy
    port, client, issue, _, _ = native
    auth = issue()
    seal(port, auth)
    with _ReplyProxy(os.environ["ZEBRA_STREAM_TEST_REDIS_URL"]) as proxy:
        bounded = RedisTransientOutput.from_url(proxy.url, resolve_authorization=lambda _: None,
                                               key_prefix=port._prefix)
        bounded._client.ping()
        proxy.reply_delay = 0.12
        started = monotonic()
        try:
            with redis_io_deadline(monotonic()+0.03), pytest.raises(RedisTimeoutError):
                bounded.collect_capacity(auth.scope, auth.capacity_policy)
            assert proxy.reply_seen.is_set() and monotonic()-started < 0.5
            assert charged(port, client, auth) == [0, 0, 0]
        finally:
            bounded.close()


def test_final_due_reschedule_error_never_early_refunds_clean_record(native, monkeypatch):
    port, client, issue, _, _ = native
    auth = issue()
    seal(port, auth)
    port.activate(auth)
    original = client.eval

    def fail(script, *args):
        if script == PUBLISH:
            marker = "redis.call('ZADD',KEYS[6],redis.call('HGET',record,'deadline'),record)"
            script = script.replace(marker, "redis.call('INCR',KEYS[5])", 1)
        return original(script, *args)

    monkeypatch.setattr(client, "eval", fail)
    with pytest.raises(TransientOutputUnavailable):
        port.publish(auth, frame(auth.scope.generation))
    before = charged(port, client, auth)
    monkeypatch.setattr(client, "eval", original)
    assert port.collect_capacity(auth.scope, auth.capacity_policy) == 0
    assert charged(port, client, auth) == before
    assert client.xlen(port._keys(auth.scope)[1]) == 1
    assert port.publish(auth, frame(auth.scope.generation))


def test_corrupt_counter_denies_existing_duplicate_and_reads(native):
    port, client, issue, _, _ = native
    auth = issue()
    seal(port, auth)
    port.activate(auth)
    first = frame(auth.scope.generation)
    port.publish(auth, first)
    ledger = port._capacity_keys(auth.scope)[0]
    client.hdel(ledger, "deployment")
    with pytest.raises(TransientOutputUnavailable, match="dirty"):
        port.publish(auth, first)
    assert port.read_after(scope=auth.scope,
        cursor=TransientResumeCursor(scope=auth.scope, durable_sequence=0),
        authorized_until=auth.expires_at).resync_required

def test_empty_reservation_cleanup_deletes_metadata_before_refund(native):
    port, client, issue, _, _ = native
    auth = issue()
    seal(port, auth)
    port._resolve(auth)
    result = port._eval(SNAPSHOT, auth.scope, uuid4().hex,
                        port._millis(auth.expires_at), auth.scope.generation.generation_id,
                        policy=auth.capacity_policy)
    assert result[0] == "ok"
    ledger, due, record = port._capacity_keys(auth.scope)
    assert client.exists(port._keys(auth.scope)[0]) == 1
    assert charged(port, client, auth) == [65536, 0, 1]
    client.hset(record, "deadline", 0)
    client.zadd(due, {record: 0})
    assert port.collect_capacity(auth.scope, auth.capacity_policy) == 1
    assert client.exists(*port._keys(auth.scope), port._keys(auth.scope)[0]+":control") == 0
    assert client.exists(record) == 0 and client.zcard(due) == 0
    assert charged(port, client, auth) == [0, 0, 0]


def test_corrupt_fractional_charge_blocks_publish_and_gc_without_refund(native):
    port, client, issue, _, _ = native
    auth = issue()
    seal(port, auth)
    port.activate(auth)
    first = frame(auth.scope.generation)
    port.publish(auth, first)
    ledger, due, record = port._capacity_keys(auth.scope)
    before = charged(port, client, auth)
    client.hset(ledger, "charge:"+record, "[1.5,0,1]")
    with pytest.raises(TransientOutputUnavailable, match="dirty"):
        port.publish(auth, first)
    client.hset(record, "dirty", "gc")
    client.zadd(due, {record: 0})
    with pytest.raises(TransientOutputUnavailable, match="recovery"):
        port.collect_capacity(auth.scope, auth.capacity_policy)
    assert client.xlen(port._keys(auth.scope)[1]) == 1
    assert charged(port, client, auth) == before


def test_older_reservation_gc_preserves_newer_revision_and_activation(native):
    port, client, issue, _, _ = native
    first = issue()
    second = issue(base=first)
    seal(port, first)
    for auth in (first, second):
        port._resolve(auth)
        result = port._eval(SNAPSHOT, auth.scope, uuid4().hex,
                            port._millis(auth.expires_at), auth.scope.generation.generation_id,
                            policy=auth.capacity_policy)
        assert result[0] == "ok"
    authority = port._keys(first.scope)[0]
    newer_revision = client.hget(authority, "revision")
    _, due, old = port._capacity_keys(first.scope)
    client.hset(old, "deadline", 0)
    client.zadd(due, {old: 0})
    assert port.collect_capacity(first.scope, first.capacity_policy) == 1
    assert client.hget(authority, "revision") == newer_revision
    port.activate(second)
    cursor = port.publish(second, frame(second.scope.generation))
    assert cursor and charged(port, client, second)[2] == 1


def test_native_issuer_tenant_run_deployment_isolation(native):
    from agent_core.domain.cloud_scope import OpaqueAuthorityScope
    port, client, issue, _, _ = native
    policy = TransientCapacityPolicy(run_slots=1, tenant_slots=2, deployment_slots=3)
    first = issue(policy)
    seal(port, first)
    port.activate(first)
    same_run = issue(policy, base=first, generation_changes={"segment_id": uuid4()})
    with pytest.raises(TransientOutputUnavailable, match="capacity"):
        port.activate(same_run)
    port.activate(issue(policy, base=first, generation_changes={"run_id": "other-run"}))
    with pytest.raises(TransientOutputUnavailable, match="capacity"):
        port.activate(issue(policy, base=first, generation_changes={"run_id": "third-run"}))
    issuer = issue(policy, base=first, authority_scope=OpaqueAuthorityScope(
        authority_issuer="other-issuer", namespace_id=first.scope.authority_scope.namespace_id))
    port.activate(issuer)
    other_tenant = issue(policy, base=first, authority_scope=OpaqueAuthorityScope(
        authority_issuer=first.scope.authority_scope.authority_issuer, namespace_id="other-tenant"))
    with pytest.raises(TransientOutputUnavailable, match="capacity"):
        port.activate(other_tenant)
    assert charged(port, client, first) == [3*65536, 0, 3]
    assert client.zcard(port._capacity_keys(first.scope)[1]) == 3
    deployment = issue(policy, base=first, deployment_namespace="other-deployment")
    with pytest.raises(TransientOutputUnavailable, match="unsealed"):
        port.activate(deployment)
    seal(port, deployment)
    port.activate(deployment)
    assert charged(port, client, deployment) == [65536, 0, 1]
    assert charged(port, client, first)[2] == 3


def test_native_old_key_ttl_drain_and_epoch_reseal(native):
    port, client, issue, _, _ = native
    auth = issue(TransientCapacityPolicy(active_seconds=1, ended_seconds=1))
    old = port._keys(auth.scope)[1]
    client.set(old, "owned legacy frame", px=100)
    with pytest.raises(TransientOutputUnavailable):
        port.seal_capacity(auth.scope, auth.capacity_policy, old_keys=(old,),
                           old_writers_quiescent=False, old_ttl_drained=False)
    with pytest.raises(TransientOutputUnavailable):
        port.seal_capacity(auth.scope, auth.capacity_policy, old_keys=(old,),
                           old_writers_quiescent=True, old_ttl_drained=True)
    sleep(0.15)
    assert client.exists(old) == 0
    seal(port, auth)
    port.activate(auth)
    port.publish(auth, frame(auth.scope.generation))
    next_epoch = issue(TransientCapacityPolicy(epoch="next", active_seconds=1), base=auth)
    with pytest.raises(TransientOutputUnavailable):
        seal(port, next_epoch)
    with pytest.raises(TransientOutputUnavailable, match="unsealed"):
        port.activate(next_epoch)
    sleep(1.05)
    assert client.exists(*port._keys(auth.scope)[1:]) == 0
    assert charged(port, client, auth)[2] == 1  # Expired bodies are not an automatic refund.
    assert port.collect_capacity(auth.scope, auth.capacity_policy) == 1
    seal(port, next_epoch)
    port.activate(next_epoch)
    assert charged(port, client, next_epoch) == [65536, 0, 1]


def test_native_lost_ledger_due_gc_removes_surviving_bodies_without_reset(native):
    port, client, issue, _, _ = native
    auth = issue(TransientCapacityPolicy(active_seconds=1))
    seal(port, auth)
    port.activate(auth)
    port.publish(auth, frame(auth.scope.generation))
    ledger, due, record = port._capacity_keys(auth.scope)
    client.delete(ledger)
    assert client.exists(record, due, *port._keys(auth.scope)[1:]) == 4
    with pytest.raises(TransientOutputUnavailable, match="unsealed"):
        port.activate(auth)
    with pytest.raises(TransientOutputUnavailable):
        seal(port, auth)
    with pytest.raises(TransientOutputUnavailable, match="recovery"):
        port.collect_capacity(auth.scope, auth.capacity_policy)
    assert client.exists(ledger) == 0  # Recovery never reconstructs a full-cap ledger.
    sleep(1.05)
    assert client.exists(*port._keys(auth.scope)[1:]) == 0
    with pytest.raises(TransientOutputUnavailable, match="recovery"):
        port.collect_capacity(auth.scope, auth.capacity_policy)
    assert client.exists(record, due) == 2 and client.exists(ledger) == 0
    with pytest.raises(TransientOutputUnavailable):
        seal(port, auth)  # Requires explicit owned inventory/TTL-drain recovery, not mutable keys.


def test_native_same_prefix_record_rebinding_cannot_delete_other_lane_or_refund(native):
    port, client, issue, _, _ = native
    first = issue()
    other = issue(base=first, generation_changes={"segment_id": uuid4()})
    seal(port, first)
    for auth in (first, other):
        port.activate(auth)
        port.publish(auth, frame(auth.scope.generation))
    ledger, due, record = port._capacity_keys(first.scope)
    _, _, other_record = port._capacity_keys(other.scope)
    keys = (*port._keys(other.scope), port._keys(other.scope)[0]+":control",
            *port._capacity_keys(other.scope)[:2], record)
    before = charged(port, client, first)
    client.hset(record, mapping={"keys": json.dumps(keys), "generation":
                other.scope.generation.generation_id, "dirty": "gc"})
    client.zadd(due, {record: 0})
    with pytest.raises(TransientOutputUnavailable, match="recovery"):
        port.collect_capacity(first.scope, first.capacity_policy)
    assert charged(port, client, first) == before
    assert all(client.xlen(port._keys(auth.scope)[1]) == 1 for auth in (first, other))
    assert client.exists(record, other_record) == 2
