"""Native Redis atomic fences, quotas and scoped resume; owned keys only."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.events import EventType
from agent_core.ports.transient_output import TransientResumeCursor
from agent_integrations.redis_transient_output import (
    RedisTransientOutput,
    TransientOutputUnavailable,
)
from redis import Redis
from redis.exceptions import ConnectionError

from tests.agent_core.test_transient_output_contract import authorization, frame, generation


@pytest.fixture
def native():
    url = os.environ.get("ZEBRA_STREAM_TEST_REDIS_URL")
    if not url:
        pytest.skip("set private native Redis dependency")
    client = Redis.from_url(url, decode_responses=True, socket_timeout=2)
    prefix = f"zebra:writer:test:{uuid4().hex}"
    known = []

    def resolve(auth):
        if not any(auth is value for value in known):
            raise TransientOutputUnavailable("unknown handle")

    adapter = RedisTransientOutput(
        client,
        resolve_authorization=resolve,
        read_authority=lambda _: datetime.now(UTC) + timedelta(seconds=30),
        key_prefix=prefix,
    )
    seed = authorization(generation())
    adapter.seal_capacity(seed.scope, seed.capacity_policy, old_keys=(),
                          old_writers_quiescent=True, old_ttl_drained=True)
    try:
        yield adapter, client, known
    finally:
        for key in client.scan_iter(match=f"{prefix}:*"):
            client.delete(key)
        client.close()


def test_constructing_authorization_grants_nothing(native):
    adapter, _, _ = native
    with pytest.raises(TransientOutputUnavailable, match="unknown handle"):
        adapter.activate(authorization(generation()))


def test_native_dedupe_mismatch_gap_full_fence_and_retirement(native):
    adapter, _, known = native
    auth = authorization(generation())
    known.append(auth)
    adapter.activate(auth)
    first = frame(auth.scope.generation, content_delta=" 你好🙂\n")
    cursor = adapter.publish(auth, first)
    assert adapter.publish(auth, first) == cursor
    with pytest.raises(TransientOutputUnavailable, match="mismatch"):
        adapter.publish(auth, first.model_copy(update={"content_delta": "changed"}))
    with pytest.raises(TransientOutputUnavailable, match="gap"):
        adapter.publish(auth, first.model_copy(update={"offset": 2}))
    wrong = auth.model_copy(
        update={"lease_fence": auth.lease_fence.model_copy(update={"owner_instance_id": "other"})}
    )
    known.append(wrong)
    with pytest.raises(TransientOutputUnavailable, match="fence"):
        adapter.activate(wrong)
    adapter.invalidate(auth.scope)
    with pytest.raises(TransientOutputUnavailable, match="retired"):
        adapter.activate(auth)
    with pytest.raises(TransientOutputUnavailable, match="not activated"):
        adapter.publish(auth, first)


def test_native_new_generation_fences_old_and_lower_token(native):
    adapter, _, known = native
    first = authorization(generation())
    known.append(first)
    adapter.activate(first)
    second_gen = first.scope.generation.model_copy(
        update={
            "generation_id": "second",
            "model_call_id": "second",
            "message_id": "message:second",
            "lease_fence": 2,
        }
    )
    second = first.model_copy(
        update={
            "scope": first.scope.model_copy(update={"generation": second_gen}),
            "lease_fence": first.lease_fence.model_copy(update={"fencing_token": 2}),
        }
    )
    known.append(second)
    adapter.activate(second)
    with pytest.raises(TransientOutputUnavailable, match="fenced"):
        adapter.publish(first, frame(first.scope.generation))
    old_gen = first.scope.generation.model_copy(update={"generation_id": "lower"})
    lower = first.model_copy(
        update={"scope": first.scope.model_copy(update={"generation": old_gen})}
    )
    known.append(lower)
    with pytest.raises(TransientOutputUnavailable, match="fence"):
        adapter.activate(lower)


def test_native_cap_expiry_fixed_retention_and_no_read_renewal(native):
    adapter, client, known = native
    auth = authorization(generation())
    known.append(auth)
    adapter.activate(auth)
    first = frame(auth.scope.generation)
    adapter._max_bytes = len(first.wire_bytes())
    adapter.publish(auth, first)
    state, stream, offsets = adapter._keys(auth.scope)
    expiry = client.pexpiretime(stream)
    barrier = adapter.capture_barrier(auth.scope)
    assert barrier.live_offset == 0
    result = adapter.read_after(
        scope=auth.scope, cursor=barrier, authorized_until=datetime.now(UTC) + timedelta(seconds=10)
    )
    assert result.frames == () and not result.resync_required
    assert client.pexpiretime(stream) == expiry
    with pytest.raises(TransientOutputUnavailable, match="capacity"):
        adapter.publish(auth, frame(auth.scope.generation, offset=1))
    assert client.xlen(stream) == 1 and client.hlen(offsets) == 1
    client.hset(state, "expiry", 1)
    with pytest.raises(TransientOutputUnavailable, match="expired"):
        adapter.publish(auth, first)
    assert adapter.read_after(
        scope=auth.scope, cursor=barrier, authorized_until=datetime.now(UTC) + timedelta(seconds=10)
    ).resync_required


def test_native_bounded_resume_scope_generation_and_cursor_gaps(native):
    adapter, client, known = native
    auth = authorization(generation())
    known.append(auth)
    adapter.activate(auth)
    for i in range(40):
        adapter.publish(auth, frame(auth.scope.generation, offset=i, content_delta="🙂" * 2000))
    cursor = TransientResumeCursor(scope=auth.scope, durable_sequence=17, durable_frame_index=2)
    deadline = datetime.now(UTC) + timedelta(seconds=10)
    first = adapter.read_after(scope=auth.scope, cursor=cursor, authorized_until=deadline)
    assert 0 < len(first.frames) < 40
    assert sum(len(value.wire_bytes()) for value in first.frames) <= 256 * 1024
    assert first.next_cursor.durable_sequence == 17 and first.next_cursor.durable_frame_index == 2
    second = adapter.read_after(
        scope=auth.scope, cursor=first.next_cursor, authorized_until=deadline
    )
    assert len(first.frames) + len(second.frames) == 40
    foreign = auth.scope.model_copy(update={"deployment_namespace": "foreign"})
    assert adapter.read_after(
        scope=foreign, cursor=cursor, authorized_until=deadline
    ).resync_required
    stream = adapter._keys(auth.scope)[1]
    client.xdel(stream, client.xrange(stream)[0][0])
    assert adapter.read_after(
        scope=auth.scope, cursor=cursor, authorized_until=deadline
    ).resync_required
    client.delete(*adapter._keys(auth.scope))  # Simulate loss of exactly owned transport keys.
    assert adapter.read_after(
        scope=auth.scope, cursor=cursor, authorized_until=deadline
    ).resync_required
    with pytest.raises(TransientOutputUnavailable, match="lost"):
        adapter.activate(auth)


def test_native_uncertain_append_and_missing_read_authority(native, monkeypatch):
    adapter, client, known = native
    auth = authorization(generation())
    known.append(auth)
    adapter.activate(auth)
    real = client.eval

    def uncertain(*args):
        real(*args)
        raise ConnectionError("reply lost after append")

    monkeypatch.setattr(client, "eval", uncertain)
    with pytest.raises(TransientOutputUnavailable, match="unavailable"):
        adapter.publish(auth, frame(auth.scope.generation))
    monkeypatch.setattr(client, "eval", real)
    assert client.xlen(adapter._keys(auth.scope)[1]) == 1
    adapter._read_authority = None
    with pytest.raises(TransientOutputUnavailable, match="read authority"):
        adapter.capture_barrier(auth.scope)
    assert adapter.read_after(
        scope=auth.scope,
        cursor=TransientResumeCursor(scope=auth.scope, durable_sequence=0),
        authorized_until=datetime.now(UTC) + timedelta(seconds=10),
    ).resync_required


def test_native_exact_decimal_fence_beyond_lua_double_and_epoch_takeover(native):
    adapter, _, known = native
    initial = authorization(generation())
    fence = initial.lease_fence.model_copy(update={"fencing_token": 2**53 + 1})
    identity = initial.scope.generation.model_copy(update={"lease_fence": 2**53 + 1})
    first = initial.model_copy(
        update={
            "scope": initial.scope.model_copy(update={"generation": identity}),
            "lease_fence": fence,
        }
    )
    known.append(first)
    adapter.activate(first)
    lower_identity = identity.model_copy(
        update={"generation_id": "lower-high", "lease_fence": 2**53}
    )
    lower = first.model_copy(
        update={
            "scope": first.scope.model_copy(update={"generation": lower_identity}),
            "lease_fence": fence.model_copy(update={"fencing_token": 2**53}),
        }
    )
    known.append(lower)
    with pytest.raises(TransientOutputUnavailable, match="fence"):
        adapter.activate(lower)
    next_identity = identity.model_copy(update={"generation_id": "fresh-epoch", "lease_fence": 1})
    fresh = first.model_copy(
        update={
            "scope": first.scope.model_copy(update={"generation": next_identity}),
            "lease_fence": fence.model_copy(
                update={"control_plane_epoch": uuid4(), "fencing_token": 1}
            ),
        }
    )
    known.append(fresh)
    adapter.activate(fresh)
    with pytest.raises(TransientOutputUnavailable, match="fenced"):
        adapter.publish(first, frame(identity))
    adapter.publish(fresh, frame(next_identity))


def test_constructed_copy_cannot_publish_and_wire_shape_is_revalidated(native):
    adapter, _, known = native
    auth = authorization(generation())
    known.append(auth)
    adapter.activate(auth)
    with pytest.raises(TransientOutputUnavailable, match="not activated"):
        adapter.publish(auth.model_copy(), frame(auth.scope.generation))
    with pytest.raises(ValueError):
        adapter.publish(
            auth, frame(auth.scope.generation).model_copy(update={"presentation": "final"})
        )


@pytest.mark.parametrize("path", ["adapter", "worker_callback"])
def test_native_redis_transport_clips_blackhole_to_publication_budget(monkeypatch, path):
    import socket
    from threading import Event, RLock, Thread
    from time import monotonic

    from agent_core.harness.public_output_lifecycle import public_output_lock
    from agent_integrations.redis_transient_deadlines import TransientRedisConnection
    from zebra_agent_worker.public_output_runtime import publication_scope

    left, right = socket.socketpair()
    eval_seen, release = Event(), Event()

    def serve():
        try:
            while True:
                data = right.recv(65536)
                if not data:
                    return
                if b"EVAL" in data:
                    eval_seen.set()
                    release.wait(1)
                    return
                right.sendall(b"+OK\r\n" * data.count(b"SETINFO"))
        finally:
            right.close()

    thread = Thread(target=serve)
    thread.start()
    monkeypatch.setattr(TransientRedisConnection, "_connect", lambda _: left)
    from agent_core.harness import public_output_lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "PUBLIC_OUTPUT_IO_SECONDS", 0.12)
    adapter = RedisTransientOutput.from_url(
        "redis://127.0.0.1:1", resolve_authorization=lambda _: None
    )
    auth = authorization(generation())
    started = monotonic()
    try:
        if path == "adapter":
            with pytest.raises(TimeoutError):
                with public_output_lock(RLock(), publication_scope):
                    with pytest.raises(TransientOutputUnavailable, match="unavailable"):
                        adapter.activate(auth)
        else:
            from unittest.mock import Mock

            from agent_core.domain.stream_admission import StreamMode
            from agent_core.harness.model_step import HarnessModelStep
            from agent_core.harness.orchestration_events import model_response_event
            from zebra_agent_worker.transient_output_runtime import TransientDeltaSink

            from tests.agent_core.test_stream_deltas import PublicStreamingProvider

            def open_call(call, attempt):
                gate = Mock()
                gate.scope = auth.scope.model_copy(
                    update={
                        "generation": auth.scope.generation.model_copy(
                            update={"model_call_id": call, "message_id": f"message:{call}"}
                        )
                    }
                )
                gate.stream_mode.return_value = StreamMode.TRANSIENT_V2
                gate.ordinary_v2.return_value = True
                gate.issue.return_value = auth.model_copy(update={"scope": gate.scope})
                return gate

            writer = TransientDeltaSink(adapter, open_call, durable_anchor=lambda: 0)
            events = []
            sink = writer.wrap(events.append)
            step = HarnessModelStep(event_sink=sink, public_call_started=writer.start_public_call)
            completion = step.request_completion([], PublicStreamingProvider(), allow_tools=True)
            sink(model_response_event(completion, attempt_number=1))
            assert writer._failed
            assert [event.event_type for event in events] == [
                EventType.MODEL_REQUEST_STARTED,
                EventType.MODEL_RESPONSE_RECEIVED,
            ]
            assert events[-1].payload["assistant_message"] == "Full response"
        assert eval_seen.is_set() and monotonic() - started < 0.3
        assert not adapter._active  # Uncertain activation is not silently retried.
    finally:
        release.set()
        adapter._client.close()
        adapter._client.connection_pool.disconnect()
        thread.join(1)
        left.close()


@pytest.mark.parametrize("transition", ["epoch", "token", "call", "close", "loss", "absent"])
def test_native_activation_cas_rejects_authority_changed_after_fresh_check(native, transition):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    adapter, client, known = native
    first = authorization(generation())
    known.append(first)
    if transition != "absent":
        adapter.activate(first)
    delayed = first.model_copy(update={"scope": first.scope.model_copy(update={
        "generation": first.scope.generation.model_copy(update={
            "generation_id": "delayed", "model_call_id": "delayed",
            "message_id": "message:delayed",
        }),
    })})
    current = [first.lease_fence]
    validated, release = Event(), Event()

    resolve_count = 0

    def delayed_resolve(auth):
        nonlocal resolve_count
        resolve_count += 1
        assert auth is delayed and auth.lease_fence == current[0]
        if resolve_count == 1:
            return  # The new first proof precedes SNAPSHOT; pause the second fresh proof.
        validated.set()
        assert release.wait(5)

    waiting = RedisTransientOutput(
        client, resolve_authorization=delayed_resolve, key_prefix=adapter._prefix,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(waiting.activate, delayed)
        try:
            assert validated.wait(2)
            if transition == "close":
                adapter.invalidate(first.scope)
            elif transition == "loss":
                client.delete(adapter._keys(first.scope)[0])
            else:
                fence = first.lease_fence.model_copy(update={
                    "control_plane_epoch": uuid4() if transition == "epoch"
                    else first.lease_fence.control_plane_epoch,
                    "fencing_token": 2 if transition == "token" else 1,
                })
                current[0] = fence
                winner = first.model_copy(update={
                    "lease_fence": fence,
                    "scope": first.scope.model_copy(update={
                        "generation": first.scope.generation.model_copy(update={
                            "generation_id": "winner", "model_call_id": "winner",
                            "message_id": "message:winner", "lease_fence": fence.fencing_token,
                        }),
                    }),
                })
                known.append(winner)
                adapter.activate(winner)
            release.set()
            with pytest.raises(TransientOutputUnavailable, match="changed"):
                pending.result(timeout=2)
            with pytest.raises(TransientOutputUnavailable, match="not activated"):
                waiting.publish(delayed, frame(delayed.scope.generation))
            if transition not in {"close", "loss"}:
                adapter.publish(winner, frame(winner.scope.generation))
        finally:
            release.set()
